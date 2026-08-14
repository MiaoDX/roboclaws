import { state, els } from "./state.js";
import { artifactHref, compactDisplayRunId, compactRunId, escapeHtml, fetchJson, formatElapsed, statusClass } from "./http-dom.js";
import { refreshSelectedRouteReadiness } from "./launch.js";
import { operatorMessageResultText, renderManualControl } from "./manual-control.js";
import { renderViews } from "./visual-workspace.js";
import { effectiveReadiness } from "./workflow-model.js";
import { renderOperatorInput, renderStartAction, resumeHelp } from "./workflow-view.js";

export function startPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
  }
  pollState();
  state.pollTimer = setInterval(pollState, 2000);
}

export async function pollState() {
  if (!state.activeRunId) {
    return;
  }
  const url = `/api/runs/${encodeURIComponent(state.activeRunId)}?selection_id=${encodeURIComponent(
    state.activeRouteId
  )}`;
  const payload = await fetchJson(url);
  if (payload.error) {
    return;
  }
  state.activeState = payload;
  if (payload.launch_selection && payload.launch_selection.id) {
    state.activeRouteId = payload.launch_selection.id;
  } else if (payload.route && payload.route.id) {
    state.activeRouteId = payload.route.id;
  }
  renderRunState(payload);
  if (!els.rawEvidence.hidden) {
    refreshRawEvidence();
  }
}

export function renderRunState(payload) {
  const route = payload.launch_selection || payload.route || state.selectedRoute || {};
  const runLabel = compactRunId(payload.run_id);
  const displayRunLabel = compactDisplayRunId(payload.display_run_id || "");
  const attemptLabel = displayRunLabel && displayRunLabel !== runLabel
    ? ` / ${displayRunLabel}`
    : "";
  document.querySelector(".top-run-bar").classList.add("run-active");
  els.runTitle.textContent = `${route.label || "Agent run"} / ${runLabel}${attemptLabel}`;
  els.runTitle.title = `${route.label || "Agent run"} / ${payload.run_id || ""}${
    payload.display_run_id && payload.display_run_id !== payload.run_id
      ? ` / ${payload.display_run_id}`
      : ""
  }`;
  els.routeStatus.textContent = payload.status_label || payload.phase || payload.status || "Running";
  els.routeStatus.className = `badge ${statusClass(payload.status || payload.phase)}`;
  els.lockStatus.textContent = `lock: ${route.lock_name || payload.backend_lock || "none"}`;
  els.elapsedStatus.textContent =
    payload.elapsed_seconds == null ? "00:00" : formatElapsed(payload.elapsed_seconds);
  els.phaseValue.textContent = payload.phase || "idle";
  els.backendLockValue.textContent = payload.backend_lock || "none";
  els.cameraAngleValue.textContent = cameraStateLabel(payload.camera_state || {});
  els.terminalValue.textContent = payload.terminal_reason || "none";

  const decision = payload.latest_public_decision_evidence || {};
  els.decisionPanel.innerHTML = `
    <strong>${escapeHtml(payload.latest_action || "No action")}</strong>
    <p>${escapeHtml(
      decision.observation_summary || "No decision yet. The agent has not called a robot tool."
    )}</p>
    <p>${escapeHtml(decision.reasoning || decision.decision || "")}</p>
    ${decision.blocked_reason ? `<p class="field-help">${escapeHtml(decision.blocked_reason)}</p>` : ""}
  `;
  renderToolPanel(payload);
  const checkerStatus = payload.checker_status || {};
  els.proofPanel.textContent = `${checkerStatus.status || "pending"}: ${
    checkerStatus.message ||
    checkerStatus.checker_log ||
    "Checker has not run yet."
  }`;
  renderAgentPromptState(payload.prompt_preview || {});
  renderArtifacts(payload.artifact_paths || []);
  renderViews(payload.latest_view_assets || {}, route);
  renderEvents(payload);
  renderControls(payload);
  renderManualControl(payload);
  renderOperatorInput(state.selectedRoute);
  renderStartAction(state.selectedRoute, effectiveReadiness(state.selectedRoute));
  renderOperatorMode(payload);
}

export function renderAgentPromptState(preview) {
  const prompt = preview.agent_kickoff_prompt || preview.prompt || "";
  if (!prompt) {
    els.agentPromptPanel.textContent =
      "No launch prompt yet. Start or attach a run to inspect the agent prompt.";
    return;
  }
  const notes = (preview.wrapper_notes || []).filter(Boolean);
  els.agentPromptPanel.innerHTML = `
    <div class="field-help">${escapeHtml(preview.summary || preview.source || "Agent kickoff prompt")}</div>
    ${
      preview.operator_prompt
        ? `<p><strong>Operator goal:</strong> ${escapeHtml(preview.operator_prompt)}</p>`
        : ""
    }
    ${notes.map((note) => `<p class="field-help">${escapeHtml(note)}</p>`).join("")}
    <details>
      <summary>Full kickoff prompt</summary>
      <pre class="prompt-preview-text">${escapeHtml(prompt)}</pre>
    </details>
  `;
}

export function renderToolPanel(payload) {
  const cameraState = payload.camera_state || {};
  const cameraSummary = cameraState.summary || "yaw 0 deg, pitch 0 deg (neutral)";
  const activeClass = cameraState.active ? "camera-active" : "camera-neutral";
  els.toolPanel.innerHTML = `
    <div class="camera-angle-row">
      <span class="camera-angle-label">Camera</span>
      <span class="camera-angle-badge ${activeClass}">${escapeHtml(cameraSummary)}</span>
    </div>
    <pre class="tool-json">${escapeHtml(JSON.stringify(payload.latest_tool_call || {}, null, 2))}</pre>
  `;
}

export function cameraStateLabel(cameraState) {
  return cameraState.summary || "yaw 0 deg, pitch 0 deg (neutral)";
}

export function renderControls(payload) {
  const controls = payload.controls || {};
  els.stopButton.disabled = !controls.stop_available;
  els.emergencyButton.disabled = !controls.emergency_stop_required;
}

export function renderOperatorMode(payload = state.activeState || {}) {
  const controls = payload.controls || {};
  if (controls.operator_handoff_paused && state.operatorMode === "steer") {
    state.operatorMode = controls.resume_available ? "resume" : "goal";
  }
  document.querySelectorAll(".operator-mode").forEach((button) => {
    const mode = button.dataset.operatorMode;
    if (mode === "steer") {
      button.disabled = Boolean(state.activeRunId && !controls.steer_available);
    } else if (mode === "resume") {
      button.hidden = !state.activeRunId || !controls.operator_handoff_paused;
      button.disabled = !controls.resume_available;
    } else {
      button.disabled = false;
    }
    button.classList.toggle("active", mode === state.operatorMode);
  });
  const messages = payload.operator_messages || {};
  if (messages.operator_resume_pending) {
    els.startHelp.textContent = `${
      messages.pending_resume_count || 1
    } resume request(s) waiting for runner continuation.`;
  } else if (controls.operator_handoff_paused && !controls.resume_available) {
    els.startHelp.textContent = resumeHelp(controls);
  } else if (messages.operator_message_pending && !controls.operator_handoff_paused) {
    els.startHelp.textContent = `${
      messages.pending_steer_count || 1
    } steer message(s) waiting for agent checkpoint.`;
  }
}

export async function sendOperatorMessage() {
  if (!state.activeRunId) {
    return;
  }
  const text = els.taskPrompt.value.trim();
  if (!text) {
    els.startHelp.textContent = "Enter operator text before sending.";
    return;
  }
  const encodedRun = encodeURIComponent(state.activeRunId);
  const endpoint = `/api/runs/${encodedRun}/messages`;
  const result = await fetchJson(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body: text }),
  });
  if (result.error) {
    els.startHelp.textContent = result.error;
    return;
  }
  els.taskPrompt.value = "";
  els.promptCount.textContent = "0 / 2000";
  els.startHelp.textContent = operatorMessageResultText(result);
  pollState();
}

export async function sendResumeRequest() {
  if (!state.activeRunId) {
    return;
  }
  const text = els.taskPrompt.value.trim();
  if (!text) {
    els.startHelp.textContent = "Enter a resume prompt before continuing the handoff.";
    return;
  }
  const result = await fetchJson(
    `/api/runs/${encodeURIComponent(state.activeRunId)}/resume`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: text }),
    }
  );
  if (result.error) {
    els.startHelp.textContent = result.error;
    return;
  }
  els.taskPrompt.value = "";
  els.promptCount.textContent = "0 / 2000";
  els.startHelp.textContent = operatorMessageResultText(result);
  pollState();
}

export function renderArtifacts(items) {
  els.artifactList.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "artifact-row";
    const link = item.href || artifactHref(item.path);
    row.innerHTML = `
      <span>${escapeHtml(item.label)}</span>
      ${link ? `<a href="${link}" target="_blank" rel="noreferrer">Open</a>` : `<span class="field-help">pending</span>`}
    `;
    els.artifactList.appendChild(row);
  }
}

export function renderEvents(payload) {
  const checkerStatus = payload.checker_status || {};
  const bits = [
    `phase=${payload.phase}`,
    payload.terminal_reason ? `reason=${payload.terminal_reason}` : "",
    `action=${payload.latest_action || "none"}`,
    `checker=${checkerStatus.status || "pending"}`,
    `outputs=${payload.display_run_dir || payload.run_dir}`,
  ].filter(Boolean);
  els.eventList.textContent = bits.join("  ");
}

export async function postRunAction(action) {
  if (!state.activeRunId) {
    return;
  }
  const result = await fetchJson(`/api/runs/${encodeURIComponent(state.activeRunId)}/${action}`, {
    method: "POST",
  });
  if (result.error) {
    els.eventList.textContent = result.error;
    return;
  }
  if (result.reason) {
    els.eventList.textContent = result.reason;
  }
  if (["stop", "emergency-stop"].includes(action)) {
    detachRunAfterStop(result);
    await refreshSelectedRouteReadiness();
    return;
  }
  pollState();
}

export function detachRunAfterStop(result) {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.activeState = result;
  renderRunState(result);
  state.activeRunId = null;
  state.activeRouteId = "";
  els.eventList.textContent =
    result.terminal_reason || result.phase || "Run stopped; backend lock released.";
  renderManualControl({});
  renderStartAction(state.selectedRoute, effectiveReadiness(state.selectedRoute));
}

export async function toggleRawEvidence() {
  if (!state.activeRunId) {
    return;
  }
  const hidden = els.rawEvidence.hidden;
  els.rawEvidence.hidden = !hidden;
  els.appShell.classList.toggle("raw-evidence-open", hidden);
  els.toggleRawButton.textContent = hidden ? "Hide Raw Evidence" : "Show Raw Evidence";
  if (hidden) {
    refreshRawEvidence({ forceStickToBottom: true });
  }
}

export async function refreshRawEvidence(options = {}) {
  const forceStickToBottom = options.forceStickToBottom === true;
  const driver = ((state.activeState && state.activeState.artifact_paths) || []).find(
    (item) => item.label === "Driver Log"
  );
  const shouldStickToBottom =
    forceStickToBottom ||
    els.rawEvidence.scrollTop + els.rawEvidence.clientHeight >=
      els.rawEvidence.scrollHeight - 24;
  const text = driver
    ? await fetch(`/api/raw/${encodeURI(driver.path)}`).then((response) => response.text())
    : "";
  els.rawEvidence.textContent = text || "No raw driver log yet.";
  if (shouldStickToBottom) {
    els.rawEvidence.scrollTop = els.rawEvidence.scrollHeight;
  }
}
