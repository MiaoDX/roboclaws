import { state, els } from "./state.js";
import { escapeHtml, fetchJson } from "./http-dom.js";
import { operatorMessageResultText } from "./manual-control.js";
import { pollState, sendOperatorMessage, sendResumeRequest, startPolling } from "./run-session.js";
import { effectiveLaunchPromptText, effectiveReadiness, intentLabel, isAgibotRoute, isRunTerminal, launchInterpretation, launchPromptText, selectedCombinationFromAxes, selectedIntent, selectedProviderLabel, selectedProviderProfile, selectedRuntimeMapPrior, selectedScenarioSetup, selectedWorkflow, workflowForRoute, workflowIntent, workflowSupportsPrior } from "./workflow-model.js";
import { evidenceLaneLabel, renderRoutes, renderSelection, renderStartAction } from "./workflow-view.js";

export function handleStartAction() {
  if (state.operatorMode === "steer") {
    sendOperatorMessage();
    return;
  }
  if (state.operatorMode === "resume") {
    confirmResume();
    return;
  }
  if (state.activeRunId && isRunTerminal()) {
    confirmNextGoal();
    return;
  }
  if (state.activeRunId) {
    els.startHelp.textContent = "Use Steer while this run is active.";
    return;
  }
  const readiness = effectiveReadiness(state.selectedRoute);
  if (readiness.attachable_run) {
    attachExistingRun(readiness.attachable_run);
    return;
  }
  confirmLaunch();
}

export function confirmResume() {
  const prompt = els.taskPrompt.value.trim();
  if (!prompt) {
    els.startHelp.textContent = "Enter a resume prompt before continuing the handoff.";
    return;
  }
  const summary = `
    <dl class="state-list">
      <dt>Run</dt><dd>${escapeHtml(state.activeRunId || "")}</dd>
      <dt>Resume</dt><dd>public operator prompt</dd>
      <dt>Queued Steer</dt><dd>not consumed as resume input</dd>
      <dt>Continuation</dt><dd>runner-owned same-run handoff resume</dd>
    </dl>
  `;
  confirmAction({
    title: "Resume Run",
    cta: "Resume Run",
    bodyHtml: summary,
    onConfirm: sendResumeRequest,
  });
}

export function attachExistingRun(run) {
  state.activeRunId = run.run_id;
  state.activeRouteId = run.selection_id || state.selectedRoute.id;
  renderStartAction(state.selectedRoute, effectiveReadiness(state.selectedRoute));
  startPolling();
}

export async function attachLatestResult() {
  const result = await fetchJson("/api/runs/latest");
  if (result.error) {
    els.eventList.textContent = result.error;
    return;
  }
  const route = state.combinations.find((item) => item.id === result.selection_id);
  if (route) {
    state.selectedRoute = route;
    state.selectedWorkflow = workflowForRoute(route);
    state.selectedIntent = route.intent_id || "";
    state.syncAxesFromRoute = true;
    renderRoutes();
    renderSelection();
  }
  state.activeRunId = result.run_id;
  state.activeRouteId = result.selection_id || (route ? route.id : state.selectedRoute.id);
  els.eventList.textContent = `Attached latest result ${result.run_id}${
    result.display_run_id ? ` / ${result.display_run_id}` : ""
  }.`;
  renderStartAction(state.selectedRoute, effectiveReadiness(state.selectedRoute));
  startPolling();
}

export function scheduleReadinessRefresh() {
  if (state.readinessTimer) {
    clearTimeout(state.readinessTimer);
  }
  state.readinessTimer = setTimeout(refreshSelectedRouteReadiness, 250);
}

export async function refreshSelectedRouteReadiness() {
  state.selectedRoute = selectedCombinationFromAxes();
  const route = state.selectedRoute;
  if (!route || !route.enabled) {
    return;
  }
  const params = new URLSearchParams({
    selection_id: route.id,
    host: "127.0.0.1",
    port: els.portInput.value || "18788",
    scenario_setup: selectedScenarioSetup(),
  });
  const workflow = selectedWorkflow();
  const prior = selectedRuntimeMapPrior(workflow);
  if (workflowSupportsPrior(workflow) && prior && prior.path) {
    params.set("runtime_map_prior", prior.path);
  }
  if (selectedProviderProfile()) {
    params.set("provider_profile", selectedProviderProfile());
  }
  if (els.contextInput.value) {
    params.set("context_json", els.contextInput.value);
  }
  if (isAgibotRoute(route)) {
    params.set("real_movement_enabled", els.realMovementGate.checked ? "true" : "false");
    params.set("localization_ready", els.localizationGate.checked ? "true" : "false");
    params.set("run_enabled", els.enablementGate.checked ? "true" : "false");
    params.set("estop_ready", els.estopGate.checked ? "true" : "false");
  }
  const readiness = await fetchJson(`/api/readiness?${params.toString()}`);
  if (readiness.error) {
    els.startHelp.textContent = readiness.error;
    return;
  }
  state.readiness[route.id] = readiness;
  renderRoutes();
  renderSelection();
}

export function confirmLaunch() {
  const route = state.selectedRoute;
  const workflow = selectedWorkflow();
  const promptSource = launchPromptText() ? "custom" : "default";
  const interpretation = launchInterpretation(route);
  const prior = selectedRuntimeMapPrior(workflow);
  const providerRows = route.provider_profile
    ? `<dt>Provider</dt><dd>${escapeHtml(selectedProviderLabel(route))}</dd>`
    : "";
  const movementRows = isAgibotRoute(route)
    ? `<dt>Movement</dt><dd>${escapeHtml(
        els.realMovementGate.checked ? "enabled" : "dry-run"
      )}</dd>`
    : "";
  const summary = `
    <dl class="state-list">
      <dt>World</dt><dd>${escapeHtml(route.world_label || route.world_id)}</dd>
      <dt>Backend</dt><dd>${escapeHtml(route.backend_label || route.backend_id)}</dd>
      <dt>Agent</dt><dd>${escapeHtml(route.agent_engine_label || route.agent_engine_id)}</dd>
      <dt>Evidence</dt><dd title="${escapeHtml(route.evidence_lane)}">${escapeHtml(evidenceLaneLabel(route))}</dd>
      <dt>Workflow</dt><dd>${escapeHtml(workflow ? workflow.label : "route launch")}</dd>
      <dt>Intent</dt><dd>${escapeHtml(interpretation.intentLabel)}</dd>
      <dt>Goal scope</dt><dd>${escapeHtml(interpretation.goalScope)}</dd>
      <dt>Checker</dt><dd>${escapeHtml(interpretation.checker)}</dd>
      <dt>Evaluation</dt><dd>${escapeHtml(interpretation.evaluation)}</dd>
      ${providerRows}
      ${workflowSupportsPrior(workflow) && prior ? `<dt>Map Prior</dt><dd>${escapeHtml(prior.path)}</dd>` : ""}
      <dt>Lock</dt><dd>${escapeHtml(route.lock_name)}</dd>
      ${movementRows}
      <dt>Prompt</dt><dd>${promptSource}</dd>
      <dt>Output</dt><dd>output/operator-console/runs/...</dd>
    </dl>
  `;
  confirmAction({
    title: "Launch Run",
    cta: "Launch Run",
    bodyHtml: summary,
    onConfirm: launchRun,
  });
}

export function confirmNextGoal() {
  const prompt = els.taskPrompt.value.trim();
  if (!prompt) {
    els.startHelp.textContent = "Enter a Next Goal before starting a linked run.";
    return;
  }
  const route = state.activeState && state.activeState.route ? state.activeState.route : state.selectedRoute;
  const summary = `
    <dl class="state-list">
      <dt>Parent Run</dt><dd>${escapeHtml(state.activeRunId || "")}</dd>
      <dt>Launch</dt><dd>${escapeHtml(route.label || state.selectedRoute.label)}</dd>
      <dt>World</dt><dd>${escapeHtml(route.world_label || route.world_id || "")}</dd>
      <dt>Backend</dt><dd>${escapeHtml(route.backend_label || route.backend_id || "")}</dd>
      <dt>Next Goal</dt><dd>custom</dd>
      <dt>Context</dt><dd>public parent artifacts only</dd>
    </dl>
  `;
  confirmAction({
    title: "Start Next Goal",
    cta: "Start Next Goal",
    bodyHtml: summary,
    onConfirm: () => sendNextGoal({ confirmed: false }),
  });
}

export async function sendNextGoal({ confirmed = false } = {}) {
  if (!state.activeRunId) {
    return;
  }
  const prompt = els.taskPrompt.value.trim();
  if (!prompt) {
    els.startHelp.textContent = "Enter a Next Goal before starting a linked run.";
    return;
  }
  const result = await fetchJson(
    `/api/runs/${encodeURIComponent(state.activeRunId)}/next-goal`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, confirmed }),
    }
  );
  if (result.error) {
    els.startHelp.textContent = result.error;
    return;
  }
  if (result.status === "confirmation_required" && !confirmed) {
    confirmAction({
      title: "Confirm Next Goal",
      cta: "Confirm Next Goal",
      body: nextGoalConfirmationText(result),
      onConfirm: () => sendNextGoal({ confirmed: true }),
    });
    return;
  }
  if (result.started_run && result.started_run.run_id) {
    state.activeRunId = result.started_run.run_id;
    state.activeRouteId = result.started_run.launch_selection
      ? result.started_run.launch_selection.id
      : result.started_run.route
      ? result.started_run.route.id
      : state.activeRouteId || state.selectedRoute.id;
    state.activeState = result.started_run;
    els.taskPrompt.value = "";
    els.promptCount.textContent = "0 / 2000";
    els.startHelp.textContent = `Started Next Goal ${state.activeRunId}.`;
    startPolling();
    renderSelection();
    return;
  }
  els.startHelp.textContent = operatorMessageResultText(result);
  pollState();
}

export function nextGoalConfirmationText(result) {
  const reason = result.queue_reason || "operator_confirmation_required";
  return (
    "This parent run needs explicit confirmation before a linked Next Goal starts.\n\n" +
    `Reason: ${reason}\n\n` +
    "Confirm only if the parent artifacts are sufficient and any required movement gates are accepted."
  );
}

// Shared confirmation modal. Pass `body` for plain text or `bodyHtml` for
// pre-escaped markup. Routes the styled <dialog> for every destructive or
// launch action instead of a native browser prompt.

export function confirmAction({ title, cta, body, bodyHtml, onConfirm }) {
  els.confirmTitle.textContent = title;
  els.confirmAction.textContent = cta;
  if (bodyHtml != null) {
    els.confirmBody.innerHTML = bodyHtml;
  } else {
    els.confirmBody.textContent = body || "";
  }
  els.confirmDialog.showModal();
  els.confirmDialog.addEventListener(
    "close",
    () => {
      if (els.confirmDialog.returnValue === "confirm") {
        onConfirm();
      }
    },
    { once: true }
  );
}

export function launchRequestBody(route = state.selectedRoute) {
  const workflow = selectedWorkflow();
  const prior = selectedRuntimeMapPrior(workflow);
  const overrides = launchOverrides(route);
  if (workflowSupportsPrior(workflow) && prior && prior.path) {
    overrides.runtime_map_prior = prior.path;
  }
  return {
    world_id: route.world_id,
    backend_id: route.backend_id,
    intent_id: workflowIntent(workflow) || selectedIntent(),
    agent_engine_id: route.agent_engine_id,
    provider_profile: selectedProviderProfile(),
    evidence_lane: route.evidence_lane,
    scenario_setup: selectedScenarioSetup(),
    prompt: effectiveLaunchPromptText(route),
    workflow_id: workflow ? workflow.id : "",
    overrides,
    env_overrides: launchEnvOverrides(route),
    gates: {
      localization_ready: els.localizationGate.checked,
      run_enabled: els.enablementGate.checked,
      estop_ready: els.estopGate.checked,
    },
  };
}

export function launchOverrides(route = state.selectedRoute) {
  const overrides = {
    seed: els.seedInput.value || "7",
    host: "127.0.0.1",
    port: els.portInput.value || "18788",
  };
  if (selectedScenarioSetup() !== "baseline" && els.relocationCountInput.value) {
    overrides.relocation_count = els.relocationCountInput.value;
  }
  if (els.contextInput.value) {
    overrides.context_json = els.contextInput.value;
  }
  if (isAgibotRoute(route)) {
    overrides.real_movement_enabled = els.realMovementGate.checked ? "true" : "false";
  }
  return overrides;
}

export function launchEnvOverrides(route = state.selectedRoute) {
  if (route.agent_engine_id === "openai-agents-sdk") {
    return {
      ROBOCLAWS_PROVIDER_PROFILE: selectedProviderProfile(),
    };
  }
  return {};
}

export async function refreshPromptPreview() {
  const route = state.selectedRoute;
  if (!route || !route.enabled || state.activeRunId || state.operatorMode !== "goal") {
    return;
  }
  els.promptPreviewSummary.textContent = "Rendering agent prompt preview...";
  const result = await fetchJson("/api/prompt-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(launchRequestBody(route)),
  });
  if (result.error) {
    els.promptPreviewSummary.textContent = result.error;
    els.promptPreviewText.textContent = "";
    return;
  }
  renderPromptPreview(result);
}

export function renderPromptPreview(preview) {
  const text = preview.agent_kickoff_prompt || preview.prompt || "";
  const notes = (preview.wrapper_notes || []).filter(Boolean);
  const noteText = notes.length ? ` ${notes.join(" ")}` : "";
  els.promptPreviewSummary.textContent = `${preview.summary || "Agent kickoff prompt"}.${
    noteText
  }`;
  els.promptPreviewText.textContent = text || "No agent prompt preview is available.";
}

export async function launchRun() {
  const route = state.selectedRoute;
  const body = launchRequestBody(route);

  const result = await fetchJson("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (result.error) {
    els.startHelp.textContent = result.error;
    return;
  }
  state.activeRunId = result.run_id;
  state.activeRouteId = route.id;
  renderStartAction(state.selectedRoute, effectiveReadiness(state.selectedRoute));
  startPolling();
}
