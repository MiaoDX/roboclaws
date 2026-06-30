const state = {
  worlds: [],
  combinations: [],
  evidenceLanes: [],
  readiness: {},
  runtime: { tasks: [], summary: {} },
  selectedWorld: null,
  selectedRoute: null,
  activeRunId: null,
  activeRouteId: "",
  activeState: null,
  operatorMode: "goal",
  pollTimer: null,
  readinessTimer: null,
  activeView: "overview",
  selectedIntent: "",
  setupSelectionKey: "",
  syncAxesFromRoute: false,
  manualControlPending: false,
};

const MANUAL_CONTROL_STEP_M = 0.25;
const MANUAL_CONTROL_TURN_DEG = 15;
const DEFAULT_UI_INTENT = "open-ended";

const els = {
  appShell: document.querySelector(".app-shell"),
  routeList: document.getElementById("route-list"),
  backendInput: document.getElementById("backend-input"),
  agentEngineInput: document.getElementById("agent-engine-input"),
  evidenceLaneInput: document.getElementById("evidence-lane-input"),
  providerProfileFields: document.getElementById("provider-profile-fields"),
  providerProfileInput: document.getElementById("provider-profile-input"),
  providerProfileHelp: document.getElementById("provider-profile-help"),
  taskPrompt: document.getElementById("prompt-input"),
  promptLabel: document.getElementById("prompt-label"),
  promptHelp: document.getElementById("prompt-copy"),
  promptCount: document.getElementById("char-count"),
  intentFields: document.getElementById("intent-fields"),
  intentInput: document.getElementById("intent-input"),
  intentPreview: document.getElementById("intent-preview"),
  seedInput: document.getElementById("seed-input"),
  scenarioSetupInput: document.getElementById("scenario-setup-input"),
  relocationCountField: document.getElementById("relocation-count-field"),
  relocationCountInput: document.getElementById("relocation-count-input"),
  portInput: document.getElementById("port-input"),
  selectedRouteSummary: document.getElementById("selected-route-summary"),
  commonFields: document.getElementById("common-fields"),
  agibotFields: document.getElementById("agibot-fields"),
  agibotGateFields: document.getElementById("agibot-gate-fields"),
  contextInput: document.getElementById("context-json-input"),
  localizationGate: document.getElementById("localization-gate"),
  enablementGate: document.getElementById("enablement-gate"),
  estopGate: document.getElementById("estop-gate"),
  realMovementGate: document.getElementById("real-movement-gate"),
  gateList: document.getElementById("gate-list"),
  commandPreview: document.getElementById("command-preview"),
  startButton: document.getElementById("start-button"),
  startHelp: document.getElementById("start-error"),
  runTitle: document.getElementById("run-title"),
  routeStatus: document.getElementById("route-status"),
  lockStatus: document.getElementById("lock-status"),
  elapsedStatus: document.getElementById("elapsed-status"),
  latestResultButton: document.getElementById("latest-result-button"),
  backgroundTasksButton: document.getElementById("background-tasks-button"),
  stopButton: document.getElementById("stop-button"),
  emergencyButton: document.getElementById("emergency-button"),
  manualControlPanel: document.getElementById("manual-control-panel"),
  manualControlStatus: document.getElementById("manual-control-status"),
  manualControlButtons: Array.from(document.querySelectorAll("[data-control-action]")),
  phaseValue: document.getElementById("phase-value"),
  backendLockValue: document.getElementById("backend-lock-value"),
  cameraAngleValue: document.getElementById("camera-angle-value"),
  terminalValue: document.getElementById("terminal-value"),
  decisionPanel: document.getElementById("decision-state"),
  toolPanel: document.getElementById("tool-state"),
  proofPanel: document.getElementById("proof-state"),
  agentPromptPanel: document.getElementById("agent-prompt-state"),
  artifactList: document.getElementById("artifact-list"),
  promptPreviewPanel: document.getElementById("prompt-preview-panel"),
  promptPreviewButton: document.getElementById("prompt-preview-button"),
  promptPreviewSummary: document.getElementById("prompt-preview-summary"),
  promptPreviewText: document.getElementById("prompt-preview-text"),
  eventList: document.getElementById("event-log"),
  rawEvidence: document.getElementById("raw-evidence"),
  toggleRawButton: document.getElementById("toggle-raw-button"),
  confirmDialog: document.getElementById("confirm-dialog"),
  confirmTitle: document.getElementById("confirm-title"),
  confirmAction: document.getElementById("confirm-action"),
  confirmBody: document.getElementById("confirm-body"),
  imageDialog: document.getElementById("image-dialog"),
  imageDialogTitle: document.getElementById("image-dialog-title"),
  imageDialogPath: document.getElementById("image-dialog-path"),
  imageDialogImg: document.getElementById("image-dialog-img"),
};

async function boot() {
  const payload = await fetchJson("/api/routes");
  state.evidenceLanes = payload.evidence_lanes || [];
  state.combinations = payload.combinations || [];
  state.worlds = orderedVisibleWorlds(payload.worlds || []);
  state.readiness = payload.readiness || {};
  state.runtime = payload.runtime || { tasks: [], summary: {} };
  state.selectedRoute =
    preferredPreviewCombination(state.combinations) ||
    preferredDefaultCombination(combinationsForWorld(state.worlds[0] && state.worlds[0].id)) ||
    preferredDefaultCombination(state.combinations) ||
    state.combinations[0];
  state.selectedWorld = state.worlds[0] || null;
  if (state.selectedRoute) {
    state.selectedWorld =
      state.worlds.find((world) => world.id === state.selectedRoute.world_id) || state.selectedWorld;
    state.selectedIntent = state.selectedRoute.intent_id || "";
    state.syncAxesFromRoute = true;
  }
  renderRoutes();
  renderSelection();
  renderBackgroundTaskButton();
  bindEvents();
  renderViewModes();
}

function orderedVisibleWorlds(worlds) {
  return worlds
    .map((world, index) => ({
      world,
      index,
      enabledLaunchCount: combinationsForWorld(world.id).filter((item) => item.enabled).length,
    }))
    .filter((item) => item.enabledLaunchCount > 0)
    .sort((left, right) => {
      const leftMolmo = isMolmospacesWorld(left.world);
      const rightMolmo = isMolmospacesWorld(right.world);
      if (leftMolmo !== rightMolmo) {
        return leftMolmo ? 1 : -1;
      }
      return left.index - right.index;
    })
    .map((item) => item.world);
}

function isMolmospacesWorld(world) {
  return world.id.startsWith("molmospaces/") || (world.tags || []).includes("molmospaces");
}

function bindEvents() {
  els.taskPrompt.addEventListener("input", () => {
    els.promptCount.textContent = `${els.taskPrompt.value.length} / 2000`;
    renderSelection();
  });
  els.intentInput.addEventListener("change", () => {
    state.selectedIntent = els.intentInput.value;
    renderSelection();
  });
  [
    els.contextInput,
    els.portInput,
    els.backendInput,
    els.agentEngineInput,
    els.evidenceLaneInput,
    els.providerProfileInput,
    els.localizationGate,
    els.enablementGate,
    els.estopGate,
    els.realMovementGate,
  ].forEach((input) => {
    input.addEventListener("input", renderSelection);
    input.addEventListener("input", renderRoutes);
    input.addEventListener("input", scheduleReadinessRefresh);
    input.addEventListener("change", renderSelection);
    input.addEventListener("change", renderRoutes);
    input.addEventListener("change", refreshSelectedRouteReadiness);
  });
  [els.scenarioSetupInput, els.relocationCountInput].forEach((input) => {
    input.addEventListener("input", () => {
      renderSelection();
      renderRoutes();
      scheduleReadinessRefresh();
    });
    input.addEventListener("change", () => {
      renderSelection();
      renderRoutes();
      refreshSelectedRouteReadiness();
    });
  });
  els.startButton.addEventListener("click", handleStartAction);
  els.promptPreviewButton.addEventListener("click", refreshPromptPreview);
  els.latestResultButton.addEventListener("click", attachLatestResult);
  els.backgroundTasksButton.addEventListener("click", refreshRuntimeTasks);
  els.manualControlButtons.forEach((button) => {
    button.addEventListener("click", () => postManualControl(button.dataset.controlAction || ""));
  });
  els.stopButton.addEventListener("click", () => {
    confirmAction({
      title: "Stop Run",
      cta: "Stop Run",
      body:
        "Stop this run? The console will terminate the active process and preserve the current artifacts.",
      onConfirm: () => postRunAction("stop"),
    });
  });
  els.emergencyButton.addEventListener("click", () => {
    confirmAction({
      title: "Emergency Stop",
      cta: "Trigger Emergency Stop",
      body:
        "Trigger the real-robot emergency stop path now. This ends the run and requires human takeover before another run.",
      onConfirm: () => postRunAction("emergency-stop"),
    });
  });
  document.querySelectorAll(".operator-mode").forEach((button) => {
    button.addEventListener("click", () => {
      state.operatorMode = button.dataset.operatorMode || "goal";
      renderSelection();
    });
  });
  els.toggleRawButton.addEventListener("click", toggleRawEvidence);
  document.querySelectorAll(".view-mode").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeView = button.dataset.view;
      renderViewModes();
    });
  });
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyVisualPath(button.dataset.copy || ""));
  });
}

function renderRoutes() {
  els.routeList.innerHTML = "";
  for (const world of state.worlds) {
    const worldCombinations = combinationsForWorld(world.id);
    const enabledCount = worldCombinations.filter((item) => item.enabled).length;
    const button = document.createElement("button");
    const selectable = enabledCount > 0;
    const active = state.selectedWorld && world.id === state.selectedWorld.id;
    const display = selectable
      ? { label: world.availability === "experimental" ? "EXPERIMENTAL" : "READY", className: world.availability === "experimental" ? "warning" : "ready" }
      : { label: "UNAVAILABLE", className: "blocked" };
    button.type = "button";
    button.className = `route-card${active ? " active" : ""}`;
    button.dataset.worldId = world.id;
    button.disabled = !selectable;
    button.innerHTML = `
      <div class="route-card-title">
        <span>${escapeHtml(world.label)}</span>
        <span class="badge ${display.className}">${display.label}</span>
      </div>
      <div class="meta-label">${escapeHtml((world.tags || []).join(" / "))}</div>
      <div>${escapeHtml((world.available_backends || []).join(", "))}</div>
      <div class="field-help">${enabledCount} launch option${enabledCount === 1 ? "" : "s"}</div>
    `;
    button.addEventListener("click", () => {
      state.selectedWorld = world;
      state.selectedRoute = preferredDefaultCombination(combinationsForWorld(world.id));
      state.selectedIntent = state.selectedRoute ? state.selectedRoute.intent_id : "";
      state.syncAxesFromRoute = true;
      renderRoutes();
      renderSelection();
      refreshSelectedRouteReadiness();
    });
    els.routeList.appendChild(button);
  }
}

function combinationsForWorld(worldId) {
  return state.combinations.filter((item) => item.world_id === worldId);
}

function preferredDefaultCombination(combinations) {
  return (
    combinations.find((item) => item.enabled && item.intent_id === DEFAULT_UI_INTENT) ||
    combinations.find((item) => item.enabled) ||
    combinations[0]
  );
}

function preferredPreviewCombination(combinations) {
  return preferredDefaultCombination(combinations.filter(routeHasPreviewAssets));
}

function routeHasPreviewAssets(route) {
  return Boolean(route && route.preview_assets && Object.keys(route.preview_assets).length);
}

function selectedCombinationFromAxes() {
  const worldId = state.selectedWorld && state.selectedWorld.id;
  const backendId = els.backendInput.value;
  const intentId = els.intentInput.value || state.selectedIntent;
  const agentEngineId = els.agentEngineInput.value;
  const evidenceLane = els.evidenceLaneInput.value || "world-public-labels";
  const axisCandidates = combinationsForWorld(worldId).filter(
    (item) =>
      item.backend_id === backendId &&
      item.intent_id === intentId &&
      item.agent_engine_id === agentEngineId
  );
  const candidates = axisCandidates.filter(
    (item) =>
      item.evidence_lane === evidenceLane
  );
  const providerProfile = els.providerProfileInput.value;
  return (
    candidates.find(
      (item) => item.enabled && (!item.provider_profile || item.provider_profile === providerProfile)
    ) ||
    candidates.find((item) => item.enabled) ||
    axisCandidates.find(
      (item) => item.enabled && (!item.provider_profile || item.provider_profile === providerProfile)
    ) ||
    axisCandidates.find((item) => item.enabled) ||
    candidates[0] ||
    axisCandidates[0] ||
    state.selectedRoute
  );
}

function renderSelection() {
  renderAxisSelectors();
  const route = selectedCombinationFromAxes();
  state.selectedRoute = route;
  if (!route) {
    return;
  }
  const readiness = effectiveReadiness(route);
  renderRouteFields(route);
  renderSelectedRouteSummary(route, readiness);
  ensureActiveViewAvailable(route);
  renderViewModes(route);
  renderIntentSelector(route);
  renderScenarioSetup(route);
  renderOperatorInput(route);
  renderSelectedScenePreview(route);

  const gates = readiness.gates || route.gates || [];
  els.gateList.innerHTML = "";
  for (const gate of gates) {
    const gateReady = gate.status === "ready";
    const display = gateBadgeDisplay(gate);
    const row = document.createElement("div");
    row.className = "gate-row";
    row.innerHTML = `
      <span>${escapeHtml(gate.label)}</span>
      <span class="badge ${display.className}">${display.label}</span>
      ${
        gate.message && (!gateReady || gate.evidence)
          ? `<span class="field-help">${escapeHtml(gate.message)}</span>`
          : ""
      }
      ${gate.evidence ? `<span class="field-help">${escapeHtml(gate.evidence)}</span>` : ""}
    `;
    els.gateList.appendChild(row);
  }
  if (!gates.length) {
    els.gateList.textContent = "No route-specific gates.";
  }

  els.commandPreview.textContent = commandPreview(route);
  renderStartAction(route, readiness);
}

function renderAxisSelectors() {
  const worldId = state.selectedWorld && state.selectedWorld.id;
  const combos = combinationsForWorld(worldId);
  const syncFromRoute = state.syncAxesFromRoute;
  const route = state.selectedRoute;
  const backendOptions = uniqueOptions(combos, "backend_id", "backend_label");
  renderSelectOptions(
    els.backendInput,
    backendOptions,
    syncFromRoute && route
      ? route.backend_id
      : currentSelectValue(els.backendInput, backendOptions, route && route.backend_id)
  );
  const agentOptions = uniqueOptions(combos, "agent_engine_id", "agent_engine_label");
  renderSelectOptions(
    els.agentEngineInput,
    agentOptions,
    syncFromRoute && route
      ? route.agent_engine_id
      : currentSelectValue(els.agentEngineInput, agentOptions, route && route.agent_engine_id)
  );
  const intentOptions = intentOptionsForCurrentAxes(combos);
  renderSelectOptions(
    els.intentInput,
    intentOptions,
    syncFromRoute && route
      ? route.intent_id
      : currentSelectValue(
          els.intentInput,
          intentOptions,
          state.selectedIntent || (route && route.intent_id)
        )
  );
  const laneOptions = evidenceLaneOptions(combos);
  renderSelectOptions(
    els.evidenceLaneInput,
    laneOptions,
    syncFromRoute && route
      ? route.evidence_lane
      : currentSelectValue(els.evidenceLaneInput, laneOptions, route && route.evidence_lane)
  );
  state.syncAxesFromRoute = false;
  const selected = selectedCombinationFromAxes();
  renderProviderProfileOptions(selected);
}

function currentSelectValue(select, options, fallbackValue = "") {
  const current = select.value || "";
  if (current && options.some((option) => option.value === current)) {
    return current;
  }
  if (fallbackValue && options.some((option) => option.value === fallbackValue)) {
    return fallbackValue;
  }
  return current || fallbackValue || "";
}

function uniqueOptions(items, valueKey, labelKey, labelFn) {
  const seen = new Map();
  for (const item of items) {
    const value = item[valueKey] || "";
    if (!value || seen.has(value)) {
      continue;
    }
    const rawLabel = item[labelKey] || value;
    seen.set(value, {
      value,
      label: labelFn ? labelFn(rawLabel) : rawLabel,
      disabled: false,
    });
  }
  return [...seen.values()];
}

function intentOptionsForCurrentAxes(combos) {
  const backendId = els.backendInput.value;
  const agentEngineId = els.agentEngineInput.value;
  const axisMatches = combos.filter(
    (item) => item.backend_id === backendId && item.agent_engine_id === agentEngineId
  );
  const scopedCombos = axisMatches.length ? axisMatches : combos;
  const intentValues = [
    ...new Set(scopedCombos.map((item) => item.intent_id).filter(Boolean)),
  ];
  return intentValues.map((value) => {
    const matching = scopedCombos.filter(
      (item) =>
        item.backend_id === backendId &&
        item.agent_engine_id === agentEngineId &&
        item.intent_id === value
    );
    const enabledMatch = matching.find((item) => item.enabled);
    const disabledMatch = matching.find((item) => !item.enabled);
    const reason = disabledMatch
      ? disabledMatch.unsupported_reason || "Unavailable for this route."
      : "Unavailable for this route.";
    return {
      value,
      label: intentLabel(value),
      disabled: !enabledMatch,
      title: enabledMatch ? "" : reason,
    };
  });
}

function evidenceLaneOptions(combos) {
  const backendId = els.backendInput.value;
  const intentId = els.intentInput.value || state.selectedIntent;
  const agentEngineId = els.agentEngineInput.value;
  const laneRows = state.evidenceLanes.length
    ? state.evidenceLanes
    : uniqueOptions(combos, "evidence_lane", "evidence_lane");
  return laneRows.map((lane) => {
    const value = lane.id || lane.value;
    const matching = combos.filter(
      (item) =>
        item.backend_id === backendId &&
        item.intent_id === intentId &&
        item.agent_engine_id === agentEngineId &&
        item.evidence_lane === value
    );
    const enabledMatch = matching.find((item) => item.enabled);
    const disabledMatch = matching.find((item) => !item.enabled);
    const reason = disabledMatch
      ? disabledMatch.unsupported_reason || "Unavailable for this route."
      : "Unavailable for this route.";
    return {
      value,
      label: lane.label || value,
      disabled: !enabledMatch,
      title: enabledMatch ? "" : reason,
    };
  });
}

function renderSelectOptions(select, options, selectedValue) {
  const previous = selectedValue || select.value || "";
  const fallback = options.find((option) => !option.disabled) || options[0];
  select.innerHTML = "";
  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.value;
    node.textContent = option.label;
    node.disabled = Boolean(option.disabled);
    if (option.title) {
      node.title = option.title;
    }
    node.selected = option.value === previous;
    select.appendChild(node);
  }
  if ((!select.value || (select.selectedOptions[0] && select.selectedOptions[0].disabled)) && fallback) {
    select.value = fallback.value;
  }
}

function renderProviderProfileOptions(route) {
  if (!route || !route.provider_profile) {
    els.providerProfileFields.hidden = true;
    els.providerProfileInput.innerHTML = "";
    els.providerProfileHelp.textContent =
      "Provider profiles are resolved through the selected agent engine.";
    return;
  }
  els.providerProfileFields.hidden = false;
  const profiles = (route.supported_provider_profiles && route.supported_provider_profiles.length)
    ? route.supported_provider_profiles
    : [...new Set(
        combinationsForWorld(route.world_id)
          .filter((item) => item.agent_engine_id === route.agent_engine_id)
          .map((item) => item.provider_profile)
          .filter(Boolean)
      )];
  const current = els.providerProfileInput.value || "";
  const selected = profiles.includes(current)
    ? current
    : route.provider_profile || route.default_provider_profile || profiles[0] || "";
  renderSelectOptions(
    els.providerProfileInput,
    profiles.map((profile) => ({ value: profile, label: providerProfileLabel(profile, route) })),
    selected
  );
  const providerRoute = selectedProviderRoute(route);
  els.providerProfileHelp.textContent = providerRoute
    ? `${providerRoute.provider_profile}; default model ${providerRoute.default_model_id}.`
    : "Provider profiles are resolved through the selected agent engine.";
}

function renderOperatorInput(route) {
  const mode = state.operatorMode;
  const hasRun = Boolean(state.activeRunId);
  if (mode === "goal") {
    els.promptLabel.textContent = hasRun ? "Next Goal" : "Goal";
    els.taskPrompt.disabled = !route.supports_prompt || (hasRun && !isRunTerminal());
    els.taskPrompt.placeholder = route.task_prompt_default || route.default_prompt || "";
    els.promptHelp.textContent = operatorGoalHelp(route);
    return;
  }
  if (mode === "steer") {
    els.promptLabel.textContent = "Steer Current Run";
    els.taskPrompt.disabled = false;
    els.taskPrompt.placeholder = "Tell the active agent what to prioritize, avoid, or check next.";
    els.promptHelp.textContent = "Steer writes an auditable active-run message for supported routes.";
    return;
  }
  if (mode === "resume") {
    els.promptLabel.textContent = "Resume With Prompt";
    els.taskPrompt.disabled = false;
    els.taskPrompt.placeholder = "Describe the manual adjustment and what the agent should do next.";
    els.promptHelp.textContent =
      "Resume records a public paused-handoff request for the runner-owned continuation path.";
    return;
  }
  state.operatorMode = "goal";
  renderOperatorInput(route);
}

function operatorGoalHelp(route) {
  if (!state.activeRunId) {
    return route.supports_prompt
      ? "Empty goal uses the route default. Prompt text is never interpreted as shell."
      : route.prompt_disabled_reason ||
          "This route cannot accept a custom prompt safely. Use the default task prompt.";
  }
  if (isRunTerminal()) {
    return "Starts a linked Next Goal run using public parent context.";
  }
  return "Goal starts a run or terminal-parent Next Goal. Use Steer while this run is active.";
}

function routeStatusDisplay(route, readiness) {
  if (!route.enabled) {
    return { label: "UNAVAILABLE", className: "blocked" };
  }
  if (readiness.can_start !== false) {
    return { label: "READY", className: "ready" };
  }
  const kind = readiness.blocker_kind || "";
  if (kind === "locked" && readiness.attachable_run) {
    return { label: "ATTACH", className: "running" };
  }
  if (kind === "locked") return { label: "LOCKED", className: "blocked" };
  if (kind === "background_task") return { label: "TASK RUNNING", className: "blocked" };
  if (kind === "mcp_port_in_use") return { label: "PORT IN USE", className: "blocked" };
  if (kind === "needs_provider") return { label: "NEEDS PROVIDER", className: "needs_action" };
  if (kind === "needs_real_movement_gate") {
    return { label: "NEEDS SAFETY GATES", className: "needs_action" };
  }
  if (kind === "needs_agibot_context") {
    return { label: "NEEDS CONTEXT", className: "needs_action" };
  }
  if (kind === "needs_route_parameter") {
    return { label: "NEEDS INPUT", className: "needs_action" };
  }
  return { label: "NEEDS ACTION", className: "needs_action" };
}

function gateBadgeDisplay(gate) {
  if (gate.status === "ready") {
    return { label: "Ready", className: "ready" };
  }
  if (gateBlocksStart(gate)) {
    return { label: "Required", className: "needs_action" };
  }
  if (gate.severity === "capability") {
    return { label: "Capability Gate", className: "warning" };
  }
  return { label: "Needs Action", className: "needs_action" };
}

function renderSelectedRouteSummary(route, readiness) {
  const status = routeStatusDisplay(route, readiness);
  const interpretation = launchInterpretation(route);
  const blockerHtml = backgroundBlockerSummaryHtml(readiness);
  els.selectedRouteSummary.innerHTML = `
    <div class="route-card-title">
      <span>${escapeHtml(route.label)}</span>
      <span class="badge ${status.className}">${status.label}</span>
    </div>
    <div class="meta-label">${escapeHtml(route.agent_engine_label || route.agent_engine_id)} / ${escapeHtml(route.evidence_lane)}</div>
    <div class="field-help">${escapeHtml(route.world_label || route.world_id)} / ${escapeHtml(route.backend_label || route.backend_id)}</div>
    <div class="field-help">${escapeHtml(interpretation.intentLabel)} / ${escapeHtml(
      interpretation.goalScope
    )}</div>
    ${blockerHtml}
  `;
  const taskLink = els.selectedRouteSummary.querySelector("[data-open-background-tasks]");
  if (taskLink) {
    taskLink.addEventListener("click", () => {
      refreshRuntimeTasks();
    });
  }
}

function backgroundBlockerSummaryHtml(readiness) {
  const blockers = readiness.background_blockers || [];
  if (!blockers.length) {
    return "";
  }
  const first = blockers[0];
  const resources = (first.resources || [])
    .map((resource) => resource.label || resource.kind)
    .filter(Boolean)
    .slice(0, 3)
    .join(" and ");
  const label = first.label || first.id || "background task";
  const text = resources
    ? `${label} is using ${resources}.`
    : `${label} is active for this route.`;
  return `
    <div class="background-blocker">
      <span>${escapeHtml(text)}</span>
      <button type="button" class="secondary mini-button" data-open-background-tasks>Refresh</button>
    </div>
  `;
}

function renderRouteFields(route) {
  const fieldGroups = new Set(route.field_groups || ["common"]);

  els.commonFields.hidden = !route.enabled || !fieldGroups.has("common");
  els.agibotFields.hidden = !fieldGroups.has("agibot");
  els.agibotGateFields.hidden = !fieldGroups.has("agibot_gates");
}

function renderScenarioSetup(route) {
  const defaults = routeDefaultOverrides(route);
  const intent = selectedIntentForRoute(route);
  const selectionKey = `${route.id}:${intent}`;
  const defaultSetup = defaultScenarioSetup(route, intent, defaults);
  if (state.setupSelectionKey !== selectionKey) {
    els.scenarioSetupInput.value = defaultSetup;
    els.relocationCountInput.value = defaults.relocation_count || "5";
    state.setupSelectionKey = selectionKey;
  }
  if (!els.relocationCountInput.value && defaults.relocation_count) {
    els.relocationCountInput.value = defaults.relocation_count;
  }
  const relocation = selectedScenarioSetup() !== "baseline";
  els.relocationCountField.hidden = !relocation;
  els.relocationCountInput.disabled = !relocation;
}

function defaultScenarioSetup(route, intent, defaults) {
  if (intent === "cleanup") {
    return route.scenario_setup || defaults.scenario_setup || "relocate-cleanup-related-objects";
  }
  return "baseline";
}

function renderIntentSelector(route) {
  state.selectedIntent = selectedIntentForRoute(route);
  els.intentFields.hidden = !route.enabled;
  els.intentInput.disabled = false;
  const interpretation = launchInterpretation(route);
  els.intentPreview.innerHTML = `
    <dl class="state-list compact">
      <dt>Goal scope</dt><dd>${escapeHtml(interpretation.goalScope)}</dd>
      <dt>Checker</dt><dd>${escapeHtml(interpretation.checker)}</dd>
      <dt>Evaluation</dt><dd>${escapeHtml(interpretation.evaluation)}</dd>
    </dl>
  `;
}

function commandPreview(route) {
  const selected = selectedIntentForRoute(route);
  let parts = [...(route.argv_preview || [])];
  if (!parts.length) {
    return "Route unavailable.";
  }
  const intentIndex = parts.findIndex((part) => String(part).startsWith("intent="));
  if (intentIndex >= 0) {
    parts[intentIndex] = `intent=${selected}`;
  }
  const providerProfile = selectedProviderProfile();
  if (providerProfile) {
    parts = withProviderProfile(parts, providerProfile);
  }
  const prompt = effectiveLaunchPromptText(route);
  if (route.supports_prompt && prompt) {
    parts.push(`prompt=${prompt}`);
  }
  return commandPartsWithSetup(parts).join(" ");
}

function withProviderProfile(parts, providerProfile) {
  const next = withoutKeys(parts, ["provider_profile"]);
  next.push(`provider_profile=${providerProfile}`);
  return next;
}

function commandPartsWithSetup(parts) {
  const setup = selectedScenarioSetup();
  const next = withoutKeys(parts, ["scenario_setup", "relocation_count"]);
  next.push(`scenario_setup=${setup}`);
  if (setup !== "baseline") {
    next.push(`relocation_count=${els.relocationCountInput.value || "5"}`);
  }
  return next;
}

function withoutKeys(parts, keys) {
  return parts.filter((part) => {
    const text = String(part);
    return !keys.some((key) => text.startsWith(`${key}=`));
  });
}

function selectedScenarioSetup() {
  return els.scenarioSetupInput.value || "baseline";
}

function routeDefaultOverrides(route) {
  const defaults = {};
  for (const item of route.default_overrides || []) {
    const text = String(item);
    const index = text.indexOf("=");
    if (index > 0) {
      defaults[text.slice(0, index)] = text.slice(index + 1);
    }
  }
  return defaults;
}

function launchPromptText() {
  if (state.operatorMode !== "goal" || state.activeRunId) {
    return "";
  }
  return els.taskPrompt.value.trim();
}

function effectiveLaunchPromptText(route = state.selectedRoute) {
  const prompt = launchPromptText();
  if (prompt) {
    return prompt;
  }
  if (route && selectedIntentForRoute(route) === "open-ended") {
    return route.task_prompt_default || route.default_prompt || "";
  }
  return "";
}

function selectedIntent() {
  const route = state.selectedRoute;
  if (!route) {
    return "";
  }
  const value = els.intentInput.value || state.selectedIntent || route.intent_id;
  return selectedIntentForRoute(route, value);
}

function selectedIntentForRoute(route, requestedIntent = "") {
  const options = intentOptions(route);
  const fallback = route.intent_id || (options[0] && options[0].id) || "";
  const candidate = requestedIntent || state.selectedIntent || fallback;
  return options.some((option) => option.id === candidate) ? candidate : fallback;
}

function intentOptions(route) {
  const options = route.intent_options || [];
  if (options.length) {
    return options;
  }
  return [route.intent_id].filter(Boolean).map((intent) => ({
    id: intent,
    label: intentLabel(intent),
    checker_id: route.checker_id || "",
    goal_scope: intent === "map-build" ? "whole-room" : "agent-declared",
    evaluation_policy: intent.replace("-", "_"),
  }));
}

function launchInterpretation(route) {
  const intent = selectedIntentForRoute(route);
  const option = intentOptions(route).find((item) => item.id === intent) || {};
  return {
    intent,
    intentLabel: option.label || intentLabel(intent),
    goalScope: goalScopeForIntent(intent, option.goal_scope || ""),
    checker: option.checker_id || route.checker_id || "",
    evaluation: option.evaluation_policy || intent.replace("-", "_"),
  };
}

function goalScopeForIntent(intent, defaultScope) {
  if (intent === "cleanup") {
    return launchPromptText() ? "prompt-scoped" : "whole-room";
  }
  if (intent === "map-build") {
    return "whole-room";
  }
  return defaultScope || "agent-declared";
}

function intentLabel(intent) {
  const labels = {
    cleanup: "Cleanup",
    "open-ended": "Open-ended",
    "map-build": "Map build",
  };
  return labels[intent] || intent;
}

function effectiveReadiness(route) {
  const base = state.readiness[route.id] || {};
  const gates = (base.gates || route.gates || []).map((gate) => ({ ...gate }));
  const lockBlocked =
    base.blocker_kind === "locked" || (base.lock && base.lock.held && !base.lock.stale);
  let blocker = "";

  if (!route.enabled) {
    return { can_start: false, blocker: route.unsupported_reason || "", gates };
  }
  if (lockBlocked) {
    blocker =
      base.blocker ||
      "Backend lock is held by another run. Open that run or wait for it to finish.";
  }

  for (const gate of gates) {
    applyLocalGateEvidence(gate);
    if (gate.status !== "ready" && gateBlocksStart(gate) && !blocker) {
      blocker = gate.message || "Required gate is incomplete.";
    }
  }

  return {
    ...base,
    can_start: !blocker,
    blocker,
    blocker_kind: blocker ? (base.blocker_kind || firstBlockingGateKind(gates)) : "",
    gates,
  };
}

function applyLocalGateEvidence(gate) {
  const localReady =
    (gate.id === "localization_ready" && els.localizationGate.checked) ||
    (gate.id === "run_enabled" && els.enablementGate.checked) ||
    (gate.id === "estop_ready" && els.estopGate.checked);

  if (isRealMovementGate(gate) && els.realMovementGate.checked) {
    gate.blocks_start = true;
    gate.required = true;
    if (gate.status !== "ready") {
      gate.kind = "needs_real_movement_gate";
      gate.message =
        "Real movement is enabled; localization, run enablement, and E-stop/manual-stop readiness must be accepted before launch.";
    }
  }

  if (!localReady) {
    return;
  }
  gate.status = "ready";
  gate.message = "Operator evidence accepted for this launch.";
}

function firstBlockingGateKind(gates) {
  const gate = gates.find((item) => item.status !== "ready" && gateBlocksStart(item));
  return gate ? gate.kind || "" : "";
}

function gateBlocksStart(gate) {
  return Boolean(gate.blocks_start || gate.required);
}

function isRunTerminal(payload = state.activeState || {}) {
  if (!state.activeRunId) {
    return false;
  }
  const controls = payload.controls || {};
  if (controls.next_goal_available === true) {
    return true;
  }
  const statusValues = [
    payload.status,
    payload.phase,
    payload.terminal_reason,
    payload.checker_status && payload.checker_status.status,
  ].map((value) => String(value || "").toLowerCase());
  return statusValues.some((value) =>
    [
      "done",
      "finished",
      "passed",
      "stopped_by_operator",
      "human_takeover_stop",
      "emergency_stopped",
      "failed",
    ].includes(value)
  );
}

function isRealMovementGate(gate) {
  return ["localization_ready", "run_enabled", "estop_ready"].includes(gate.id);
}

function renderStartAction(route, readiness) {
  const mode = state.operatorMode;
  if (mode === "steer") {
    const controls = (state.activeState && state.activeState.controls) || {};
    const enabled = Boolean(state.activeRunId && controls.steer_available);
    els.startButton.textContent = "Steer Run";
    els.startButton.disabled = !enabled;
    els.startHelp.textContent = steerHelp(controls);
    return;
  }
  if (mode === "resume") {
    const controls = (state.activeState && state.activeState.controls) || {};
    const enabled = Boolean(state.activeRunId && controls.resume_available);
    els.startButton.textContent = "Resume With Prompt";
    els.startButton.disabled = !enabled;
    els.startHelp.textContent = resumeHelp(controls);
    return;
  }
  if (state.activeRunId) {
    const terminal = isRunTerminal();
    els.startButton.textContent = terminal ? "Start Next Goal" : "Run Attached";
    els.startButton.disabled = !terminal || !route.supports_prompt;
    els.startHelp.textContent = terminal
      ? "Start a linked Next Goal from this terminal parent run."
      : activeRunHelp((state.activeState && state.activeState.controls) || {});
    return;
  }
  const attachableRun = readiness.attachable_run || null;
  els.startButton.textContent = attachableRun ? "Attach Existing Run" : "Start Agent Run";
  els.startButton.disabled = !route.enabled || (readiness.can_start === false && !attachableRun);
  const backgroundBlockerText = backgroundBlockerHelp(readiness);
  els.startHelp.textContent = attachableRun
    ? `Existing run ${attachableRun.run_id} is using this backend. Attach to watch it.`
    : backgroundBlockerText || readiness.blocker || route.unsupported_reason || "";
}

function backgroundBlockerHelp(readiness) {
  const blockers = readiness.background_blockers || [];
  if (!blockers.length) {
    return "";
  }
  const first = blockers[0];
  const resources = (first.resources || [])
    .map((resource) => resource.label || resource.kind)
    .filter(Boolean)
    .slice(0, 3)
    .join(" and ");
  return resources
    ? `Background task ${first.id} is using ${resources}. Refresh background tasks for latest status.`
    : `Background task ${first.id} is active. Refresh background tasks for latest status.`;
}

function steerHelp(controls) {
  if (!state.activeRunId) {
    return "Attach a run before steering.";
  }
  if (controls.steer_available) {
    return "Message will be written to operator_messages.jsonl for the active run.";
  }
  if (controls.operator_handoff_paused) {
    return "Steer is unavailable during paused operator handoff. Use Resume With Prompt.";
  }
  return controls.supports_operator_steer
    ? "Steer is unavailable after this run is terminal. Use Goal for Next Goal."
    : "This route does not expose active-run steering.";
}

function resumeHelp(controls) {
  if (!state.activeRunId) {
    return "Attach a paused handoff run before resuming.";
  }
  if (controls.resume_available) {
    return "Resume request will be written to operator_resume_requests.jsonl.";
  }
  if (controls.operator_handoff_paused && controls.supports_paused_handoff_resume) {
    return "Paused handoff is not currently resumable from the live runner state.";
  }
  if (controls.operator_handoff_paused) {
    return "This route has no runner-owned paused-handoff resume implementation.";
  }
  return "Resume With Prompt is available only during paused operator handoff.";
}

function activeRunHelp(controls) {
  if (controls.operator_handoff_paused) {
    return controls.resume_available
      ? `Paused handoff in ${state.activeRunId}. Use Resume With Prompt after manual control.`
      : `Paused handoff in ${state.activeRunId}. Resume is blocked for this route.`;
  }
  return `Watching active run ${state.activeRunId}. Use Steer.`;
}

function handleStartAction() {
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

function confirmResume() {
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

function attachExistingRun(run) {
  state.activeRunId = run.run_id;
  state.activeRouteId = run.selection_id || state.selectedRoute.id;
  renderStartAction(state.selectedRoute, effectiveReadiness(state.selectedRoute));
  startPolling();
}

async function attachLatestResult() {
  const result = await fetchJson("/api/runs/latest");
  if (result.error) {
    els.eventList.textContent = result.error;
    return;
  }
  const route = state.combinations.find((item) => item.id === result.selection_id);
  if (route) {
    state.selectedRoute = route;
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

function scheduleReadinessRefresh() {
  if (state.readinessTimer) {
    clearTimeout(state.readinessTimer);
  }
  state.readinessTimer = setTimeout(refreshSelectedRouteReadiness, 250);
}

async function refreshSelectedRouteReadiness() {
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

async function refreshRuntimeTasks() {
  const port = els.portInput.value || "18788";
  const payload = await fetchJson(`/api/runtime/tasks?port=${encodeURIComponent(port)}`);
  if (payload.error) {
    els.eventList.textContent = payload.error;
    return;
  }
  state.runtime = payload;
  renderBackgroundTaskButton();
  els.eventList.textContent = backgroundTaskEventText();
}

function confirmLaunch() {
  const route = state.selectedRoute;
  const promptSource = launchPromptText() ? "custom" : "default";
  const interpretation = launchInterpretation(route);
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
      <dt>Evidence</dt><dd>${escapeHtml(route.evidence_lane)}</dd>
      <dt>Intent</dt><dd>${escapeHtml(interpretation.intentLabel)}</dd>
      <dt>Goal scope</dt><dd>${escapeHtml(interpretation.goalScope)}</dd>
      <dt>Checker</dt><dd>${escapeHtml(interpretation.checker)}</dd>
      <dt>Evaluation</dt><dd>${escapeHtml(interpretation.evaluation)}</dd>
      ${providerRows}
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

function confirmNextGoal() {
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

async function sendNextGoal({ confirmed = false } = {}) {
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

function nextGoalConfirmationText(result) {
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
function confirmAction({ title, cta, body, bodyHtml, onConfirm }) {
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

function launchRequestBody(route = state.selectedRoute) {
  return {
    world_id: route.world_id,
    backend_id: route.backend_id,
    intent_id: selectedIntent(),
    agent_engine_id: route.agent_engine_id,
    provider_profile: selectedProviderProfile(),
    evidence_lane: route.evidence_lane,
    scenario_setup: selectedScenarioSetup(),
    prompt: effectiveLaunchPromptText(route),
    overrides: launchOverrides(route),
    env_overrides: launchEnvOverrides(route),
    gates: {
      localization_ready: els.localizationGate.checked,
      run_enabled: els.enablementGate.checked,
      estop_ready: els.estopGate.checked,
    },
  };
}

function launchOverrides(route = state.selectedRoute) {
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

function launchEnvOverrides(route = state.selectedRoute) {
  if (route.agent_engine_id === "openai-agents-sdk") {
    return {
      ROBOCLAWS_PROVIDER_PROFILE: selectedProviderProfile(),
    };
  }
  return {};
}

async function refreshPromptPreview() {
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

function renderPromptPreview(preview) {
  const text = preview.agent_kickoff_prompt || preview.prompt || "";
  const notes = (preview.wrapper_notes || []).filter(Boolean);
  const noteText = notes.length ? ` ${notes.join(" ")}` : "";
  els.promptPreviewSummary.textContent = `${preview.summary || "Agent kickoff prompt"}.${
    noteText
  }`;
  els.promptPreviewText.textContent = text || "No agent prompt preview is available.";
}

async function launchRun() {
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

function startPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
  }
  pollState();
  state.pollTimer = setInterval(pollState, 2000);
}

async function pollState() {
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

function renderRunState(payload) {
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

function renderAgentPromptState(preview) {
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

function renderToolPanel(payload) {
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

function cameraStateLabel(cameraState) {
  return cameraState.summary || "yaw 0 deg, pitch 0 deg (neutral)";
}

function renderControls(payload) {
  const controls = payload.controls || {};
  els.stopButton.disabled = !controls.stop_available;
  els.emergencyButton.disabled = !controls.emergency_stop_required;
}

function renderManualControl(payload = state.activeState || {}) {
  if (!els.manualControlPanel) {
    return;
  }
  const controls = payload.controls || {};
  const supports = Boolean(controls.supports_relative_navigation_control);
  const available = Boolean(controls.relative_navigation_control_available);
  const hasRun = Boolean(state.activeRunId);
  els.manualControlPanel.hidden = !hasRun && !supports;
  const disabled = state.manualControlPending || !hasRun || !available;
  for (const button of els.manualControlButtons) {
    button.disabled = disabled;
  }
  els.manualControlStatus.textContent = manualControlStatusText(payload, controls, available);
}

function manualControlStatusText(payload, controls, available) {
  if (state.manualControlPending) {
    return "Manual control request is in flight.";
  }
  const latest = payload.latest_operator_control || {};
  const response = latest.response || {};
  const action = latest.action || "";
  if (latest.error) {
    return `Manual control failed: ${latest.error}`;
  }
  if (response.error_reason || response.status === "blocked_capability") {
    return `Manual control blocked: ${response.error_reason || response.status}.`;
  }
  if (response.applied_delta) {
    return `Last operator move: ${relativeDeltaText(response.applied_delta)}; observe again before using visual evidence.`;
  }
  if (action === "observe") {
    return "Last operator action: observe.";
  }
  if (!state.activeRunId) {
    return "Attach or start a supported active run to use manual control.";
  }
  if (!controls.supports_relative_navigation_control) {
    return "This route does not expose relative navigation control.";
  }
  if (!available) {
    if (controls.operator_handoff_paused) {
      return "Manual control is unavailable for this paused handoff route.";
    }
    return "Manual control is unavailable after this run reaches a terminal state.";
  }
  if (controls.operator_handoff_paused) {
    return "Paused handoff: manual control is available before resume.";
  }
  return "Ready. Operator moves are recorded as assisted interventions.";
}

function relativeDeltaText(delta) {
  const parts = [];
  const forward = Number(delta.forward_m || 0);
  const lateral = Number(delta.lateral_m || 0);
  const yaw = Number(delta.yaw_delta_deg || 0);
  if (forward) {
    parts.push(`${formatSigned(forward)} m forward`);
  }
  if (lateral) {
    parts.push(`${formatSigned(lateral)} m lateral`);
  }
  if (yaw) {
    parts.push(`${formatSigned(yaw)} deg yaw`);
  }
  return parts.length ? parts.join(", ") : "no movement applied";
}

function formatSigned(value) {
  return `${value > 0 ? "+" : ""}${Number(value).toFixed(Math.abs(value) < 1 ? 2 : 1)}`;
}

function renderOperatorMode(payload = state.activeState || {}) {
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

async function sendOperatorMessage() {
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

async function sendResumeRequest() {
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

async function postManualControl(action) {
  if (!state.activeRunId || state.manualControlPending) {
    return;
  }
  const payload = manualControlPayload(action);
  if (!payload) {
    els.manualControlStatus.textContent = `Unsupported manual control: ${action || "unknown"}.`;
    return;
  }
  state.manualControlPending = true;
  renderManualControl(state.activeState || {});
  const result = await fetchJson(
    `/api/runs/${encodeURIComponent(state.activeRunId)}/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  state.manualControlPending = false;
  if (result.error) {
    els.manualControlStatus.textContent = result.error;
    renderManualControl(state.activeState || {});
    return;
  }
  els.manualControlStatus.textContent = manualControlResultText(result);
  await pollState();
}

function manualControlPayload(action) {
  const zero = { forward_m: 0, lateral_m: 0, yaw_delta_deg: 0 };
  const byAction = {
    forward: { ...zero, forward_m: MANUAL_CONTROL_STEP_M },
    back: { ...zero, forward_m: -MANUAL_CONTROL_STEP_M },
    left: { ...zero, lateral_m: MANUAL_CONTROL_STEP_M },
    right: { ...zero, lateral_m: -MANUAL_CONTROL_STEP_M },
    "turn-left": { ...zero, yaw_delta_deg: MANUAL_CONTROL_TURN_DEG },
    "turn-right": { ...zero, yaw_delta_deg: -MANUAL_CONTROL_TURN_DEG },
  };
  if (action === "observe") {
    return { action: "observe" };
  }
  const delta = byAction[action];
  return delta ? { action: "navigate_to_relative_pose", ...delta } : null;
}

function manualControlResultText(result) {
  const response = result.response || {};
  if (response.applied_delta) {
    return `Operator move recorded: ${relativeDeltaText(response.applied_delta)}.`;
  }
  if (result.action === "observe") {
    return "Operator observe recorded.";
  }
  return `Operator control recorded: ${result.action || "control"}.`;
}

function operatorMessageResultText(result) {
  if (result.command_type === "next_goal") {
    return `Next Goal ${result.status || "queued"} (${result.queue_reason || "queued"}).`;
  }
  if (result.command_type === "steer") {
    return `Steer message ${result.status || "queued"}; waiting for check_operator_messages.`;
  }
  if (result.command_type === "resume_with_prompt") {
    return `Resume request ${result.status || "queued"}; waiting for runner continuation.`;
  }
  return "Operator message recorded.";
}

function renderArtifacts(items) {
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

function renderBackgroundTaskButton() {
  const tasks = (state.runtime && state.runtime.tasks) || [];
  const summary = (state.runtime && state.runtime.summary) || {};
  const activeCount = Number(summary.active || tasks.length || 0);
  els.backgroundTasksButton.hidden = activeCount <= 0;
}

function backgroundTaskEventText() {
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

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

function renderViews(assets, route = state.selectedRoute) {
  const sourceAssets = assets || {};
  const displayAssets = { ...sourceAssets };
  setImageSlot(
    "fpv",
    displayAssets.fpv,
    "Missing run FPV artifact: expected robot_views/*.fpv.png."
  );
  const metricMapAsset =
    sourceAssets.runtime_map || sourceAssets.map || routePreviewAsset(route, "map");
  displayAssets.map = metricMapAsset;
  setImageSlot(
    "map",
    metricMapAsset,
    "Missing Metric Map artifact: expected runtime_metric_map_preview.png or map_bundle/preview.png."
  );
  setImageSlot(
    "topdown",
    sourceAssets.topdown || routePreviewAsset(route, "topdown"),
    "Missing run Top2Down artifact: expected a run-local topdown image."
  );
  const chaseEmptyText = routeHasView(route, "chase")
    ? "Missing run chase artifact: expected robot_views/*.chase.png."
    : "Chase view unavailable for this backend.";
  const chaseAsset = routeHasView(route, "chase")
    ? sourceAssets.chase || routePreviewAsset(route, "chase")
    : null;
  displayAssets.topdown = sourceAssets.topdown || routePreviewAsset(route, "topdown");
  displayAssets.chase = chaseAsset;
  setImageSlot("chase", displayAssets.chase, chaseEmptyText);
  setImageSlot("grounding", sourceAssets.grounding, "No grounding result yet.");
  state.latestViewAssets = displayAssets;
  ensureActiveViewAvailable(route);
  renderViewModes(route);
}

function renderSelectedScenePreview(route = state.selectedRoute) {
  if (state.activeRunId) {
    return;
  }
  const previews = route && route.preview_assets ? route.preview_assets : {};
  state.latestViewAssets = previews;
  setImageSlot("fpv", previews.fpv, "No scene FPV preview is available.");
  setImageSlot("map", previews.map, "No base Metric Map preview is available.");
  setImageSlot("topdown", previews.topdown, "No Top2Down scene preview is available.");
  setImageSlot("grounding", null, "Grounding will appear after a camera-grounded run starts.");
  const chaseEmptyText = routeHasView(route, "chase")
    ? "Chase preview will appear after a run starts."
    : "Chase view unavailable for this backend.";
  setImageSlot("chase", routeHasView(route, "chase") ? previews.chase : null, chaseEmptyText);
}

function setImageSlot(name, asset, emptyText) {
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

function routePreviewAsset(route, name) {
  const previews = route && route.preview_assets ? route.preview_assets : {};
  return previews[name] || null;
}

function imageLabel(name, asset = {}) {
  if (name === "fpv" && asset.display_source === "visual_grounding_overlay") {
    return "FPV(+Grounding)";
  }
  const labels = {
    fpv: "FPV(+Grounding)",
    map: "Metric Map",
    topdown: "Top2Down",
    grounding: "Grounding",
    chase: "Chase",
  };
  return labels[name] || name;
}

function updatePanelTitle(name, label) {
  const title = document.querySelector(`[data-panel-title="${name}"]`);
  if (title) {
    title.textContent = label;
  }
}

function updateCopyButton(name, asset) {
  const button = document.querySelector(`[data-copy="${name}"]`);
  if (!button) {
    return;
  }
  button.disabled = !asset || !asset.path;
  button.title = asset && asset.path ? asset.path : "No artifact path yet";
}

async function copyVisualPath(name) {
  const asset =
    state.latestViewAssets &&
    (name === "map"
      ? state.latestViewAssets.runtime_map || state.latestViewAssets.map
      : state.latestViewAssets[name]);
  if (!asset || !asset.path) {
    els.eventList.textContent = `${imageLabel(name)} artifact path is not available yet.`;
    return;
  }
  await copyText(asset.path);
  els.eventList.textContent = `Copied ${imageLabel(name, asset)} path.`;
}

function openImageDialog({ src, title, path }) {
  if (!src) {
    return;
  }
  els.imageDialogTitle.textContent = title;
  els.imageDialogPath.textContent = path;
  els.imageDialogImg.src = src;
  els.imageDialogImg.alt = `${title} artifact`;
  els.imageDialog.showModal();
}

function renderEvents(payload) {
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

function renderViewModes(route = state.selectedRoute) {
  const visualGrid = document.getElementById("visual-grid");
  if (!visualGrid || !route) {
    return;
  }
  const modes = routeViewModes(route);
  const activeView = state.activeView || "overview";
  visualGrid.className = `view-grid mode-${activeView}`;

  document.querySelectorAll(".view-mode").forEach((button) => {
    const enabled = modes.has(button.dataset.view);
    button.hidden = !enabled;
    button.classList.toggle("active", enabled && button.dataset.view === activeView);
  });

  const visiblePanels = visiblePanelsForView(activeView, modes, route);
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.hidden = !visiblePanels.has(panel.dataset.panel);
  });
}

function ensureActiveViewAvailable(route = state.selectedRoute) {
  if (!route) {
    return;
  }
  const modes = routeViewModes(route);
  if (!modes.has(state.activeView)) {
    state.activeView = "overview";
  }
}

function routeViewModes(route) {
  const modes = new Set(route.view_modes || ["overview", "fpv", "map", "outputs"]);
  modes.add("topdown");
  return modes;
}

function routeHasView(route, view) {
  return new Set((route && route.view_modes) || []).has(view);
}

function isAgibotRoute(route) {
  const groups = new Set((route && route.field_groups) || []);
  return Boolean(route && (route.backend_id === "agibot-gdk" || groups.has("agibot_gates")));
}

function selectedProviderProfile() {
  return (els.providerProfileInput && els.providerProfileInput.value) || "";
}

function selectedProviderRoute(route = state.selectedRoute) {
  const providerProfile = selectedProviderProfile();
  if (!providerProfile || !route || !Array.isArray(route.provider_routes)) {
    return null;
  }
  return route.provider_routes.find((item) => item.provider_profile === providerProfile) || null;
}

function selectedProviderLabel(route = state.selectedRoute) {
  const providerRoute = selectedProviderRoute(route);
  return providerRoute ? providerRoute.label : selectedProviderProfile();
}

function providerProfileLabel(profile, route = state.selectedRoute) {
  if (!route || !Array.isArray(route.provider_routes)) {
    return profile;
  }
  const providerRoute = route.provider_routes.find((item) => item.provider_profile === profile);
  return providerRoute ? providerRoute.label : profile;
}

function visiblePanelsForView(view, modes, route = state.selectedRoute) {
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

async function postRunAction(action) {
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

function detachRunAfterStop(result) {
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

async function toggleRawEvidence() {
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

async function refreshRawEvidence(options = {}) {
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

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  return response.json();
}

function artifactHref(path) {
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

function statusClass(value) {
  if (!value) return "neutral";
  const text = String(value);
  if (text.includes("pass") || text.includes("finish")) return "passed";
  if (text.includes("rate_limit")) return "failed";
  if (text.includes("fail") || text.includes("stop")) return "failed";
  if (text.includes("run") || text.includes("start")) return "running";
  return "warning";
}

function formatElapsed(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = String(Math.floor(value / 60)).padStart(2, "0");
  const rest = String(value % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

function compactRunId(runId) {
  return compactRunPart(String(runId || ""));
}

function compactDisplayRunId(displayRunId) {
  return String(displayRunId || "")
    .split("/")
    .map((part) => compactRunPart(part))
    .join("/");
}

function compactRunPart(part) {
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

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

boot();
