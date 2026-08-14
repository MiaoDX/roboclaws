import { state, els } from "./state.js";
import { refreshRuntimeTasks } from "./background-tasks.js";
import { escapeHtml } from "./http-dom.js";
import { refreshSelectedRouteReadiness } from "./launch.js";
import { ensureActiveViewAvailable, renderSelectedScenePreview, renderViewModes } from "./visual-workspace.js";
import { combinationsForWorld, currentSelectValue, defaultScenarioSetup, effectiveLaunchPromptText, effectiveReadiness, evidenceLaneOptions, gateBlocksStart, intentLabel, intentOptions, intentOptionsForCurrentAxes, isRunTerminal, launchInterpretation, preferredDefaultCombination, preferredWorkflowForWorld, providerProfileLabel, routeDefaultOverrides, routeForWorkflow, selectedCombinationFromAxes, selectedIntent, selectedIntentForRoute, selectedProviderProfile, selectedProviderRoute, selectedRuntimeMapPrior, selectedScenarioSetup, selectedWorkflow, uniqueOptions, workflowActionsForWorld, workflowHasRoute, workflowIntent, workflowIsStartable, workflowSupportsPrior } from "./workflow-model.js";

export function renderRoutes() {
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
      state.selectedWorkflow = preferredWorkflowForWorld(world);
      state.selectedRoute =
        routeForWorkflow(state.selectedWorkflow, world) ||
        preferredDefaultCombination(combinationsForWorld(world.id));
      state.selectedIntent = workflowIntent(state.selectedWorkflow) || (state.selectedRoute ? state.selectedRoute.intent_id : "");
      state.syncAxesFromRoute = true;
      renderRoutes();
      renderSelection();
      refreshSelectedRouteReadiness();
    });
    els.routeList.appendChild(button);
  }
}

export function renderSelection() {
  if (!state.selectedWorkflow) {
    state.selectedWorkflow = preferredWorkflowForWorld();
  }
  const workflowRoute = routeForWorkflow(state.selectedWorkflow);
  if (workflowRoute && !state.syncAxesFromRoute) {
    state.selectedRoute = workflowRoute;
    state.selectedIntent = workflowIntent(state.selectedWorkflow);
    state.syncAxesFromRoute = true;
  }
  renderAxisSelectors();
  const route = selectedCombinationFromAxes();
  state.selectedRoute = route;
  if (!route) {
    return;
  }
  const readiness = effectiveReadiness(route);
  renderRouteFields(route);
  renderSceneState(route);
  renderWorkflowActions(route, readiness);
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

export function renderSceneState(route) {
  const workflow = selectedWorkflow();
  const prior = selectedRuntimeMapPrior(workflow);
  const world = state.selectedWorld || {};
  const backend = route ? route.backend_label || route.backend_id : world.default_backend || "";
  if (prior) {
    const staleness = prior.staleness || prior.compatibility || "";
    const stalenessLine =
      staleness && staleness !== "compatible"
        ? `<p class="field-help">Staleness: ${escapeHtml(staleness)}</p>`
        : "";
    els.mapPriorState.innerHTML = `
      <strong>${escapeHtml(prior.status || "selected")}</strong>
      <p>${escapeHtml(prior.path || "")}</p>
      <p class="field-help">${escapeHtml(prior.source || "Runtime Map Prior Snapshot")}</p>
      ${stalenessLine}
    `;
  } else {
    els.mapPriorState.innerHTML = `
      <strong>No recommended prior</strong>
      <p>Open Task and Cleanup can launch without a prior, or use Build Map and select an accepted Runtime Map Prior Snapshot later.</p>
      <p class="field-help">${escapeHtml(world.label || world.id || "scene")} / ${escapeHtml(backend)}</p>
    `;
  }
}

export function renderWorkflowActions(route, readiness) {
  const workflows = workflowActionsForWorld();
  els.workflowActionList.innerHTML = "";
  for (const workflow of workflows) {
    const active = selectedWorkflow() && workflow.id === selectedWorkflow().id;
    const startable = workflowIsStartable(workflow);
    const status = workflowStatusDisplay(workflow, route, readiness);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `workflow-action${active ? " active" : ""}`;
    button.dataset.workflowId = workflow.id;
    button.disabled = !startable;
    button.innerHTML = `
      <span class="workflow-action-title">${escapeHtml(workflow.label)}</span>
      <span class="badge ${status.className}">${status.label}</span>
      <span class="field-help">${escapeHtml(workflowCoverageText(workflow))}</span>
      ${workflow.disabled_reason && !startable ? `<span class="field-help">${escapeHtml(workflow.disabled_reason)}</span>` : ""}
    `;
    button.addEventListener("click", () => {
      state.selectedWorkflow = workflow;
      const nextRoute = routeForWorkflow(workflow);
      if (nextRoute) {
        state.selectedRoute = nextRoute;
        state.selectedIntent = workflowIntent(workflow);
        state.syncAxesFromRoute = true;
      }
      renderSelection();
      refreshSelectedRouteReadiness();
    });
    els.workflowActionList.appendChild(button);
  }
}

export function workflowStatusDisplay(workflow, route, readiness) {
  if (!workflowHasRoute(workflow)) {
    return { label: "UNAVAILABLE", className: "blocked" };
  }
  if (!workflowIsStartable(workflow)) {
    return { label: "UNAVAILABLE", className: "blocked" };
  }
  if (selectedWorkflow() && workflow.id === selectedWorkflow().id && readiness.can_start === false) {
    return routeStatusDisplay(route, readiness);
  }
  return { label: "READY", className: "ready" };
}

export function workflowCoverageText(workflow) {
  const coverage = workflow.coverage || {};
  return `${coverage.owner_type || "coverage"}: ${coverage.owner_id || "unowned"}`;
}

export function renderAxisSelectors() {
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

export function renderSelectOptions(select, options, selectedValue) {
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

export function renderProviderProfileOptions(route) {
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

export function renderOperatorInput(route) {
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

export function operatorGoalHelp(route) {
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

export function routeStatusDisplay(route, readiness) {
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

export function gateBadgeDisplay(gate) {
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

export function renderSelectedRouteSummary(route, readiness) {
  const status = routeStatusDisplay(route, readiness);
  const interpretation = launchInterpretation(route);
  const workflow = selectedWorkflow();
  const blockerHtml = backgroundBlockerSummaryHtml(readiness);
  const evidenceLabel = evidenceLaneLabel(route);
  els.selectedRouteSummary.innerHTML = `
    <div class="route-card-title">
      <span>${escapeHtml(workflow ? workflow.label : route.label)}</span>
      <span class="badge ${status.className}">${status.label}</span>
    </div>
    <div class="meta-label" title="${escapeHtml(route.evidence_lane)}">${escapeHtml(route.agent_engine_label || route.agent_engine_id)} / ${escapeHtml(evidenceLabel)}</div>
    <div class="field-help">${escapeHtml(route.world_label || route.world_id)} / ${escapeHtml(route.backend_label || route.backend_id)}</div>
    <div class="field-help">${escapeHtml(interpretation.intentLabel)} / ${escapeHtml(
      interpretation.goalScope
    )}</div>
    ${workflow ? `<div class="field-help">${escapeHtml(workflowCoverageText(workflow))}</div>` : ""}
    ${blockerHtml}
  `;
  const taskLink = els.selectedRouteSummary.querySelector("[data-open-background-tasks]");
  if (taskLink) {
    taskLink.addEventListener("click", () => {
      refreshRuntimeTasks();
    });
  }
}

export function evidenceLaneLabel(route) {
  if (!route) {
    return "";
  }
  if (route.evidence_lane_label) {
    return route.evidence_lane_label;
  }
  const lane = state.evidenceLanes.find((item) => item.id === route.evidence_lane);
  return (lane && lane.label) || route.evidence_lane || "";
}

export function backgroundBlockerSummaryHtml(readiness) {
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

export function renderRouteFields(route) {
  const fieldGroups = new Set(route.field_groups || ["common"]);

  els.commonFields.hidden = !route.enabled || !fieldGroups.has("common");
  els.agibotFields.hidden = !fieldGroups.has("agibot");
  els.agibotGateFields.hidden = !fieldGroups.has("agibot_gates");
}

export function renderScenarioSetup(route) {
  const defaults = routeDefaultOverrides(route);
  const workflow = selectedWorkflow();
  const intent = workflowIntent(workflow) || selectedIntentForRoute(route);
  const selectionKey = `${route.id}:${intent}:${workflow ? workflow.id : ""}`;
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

export function renderIntentSelector(route) {
  const workflow = selectedWorkflow();
  state.selectedIntent = workflowIntent(workflow) || selectedIntentForRoute(route);
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

export function commandPreview(route) {
  const workflow = selectedWorkflow();
  const selected = workflowIntent(workflow) || selectedIntentForRoute(route);
  let parts = [...(route.argv_preview || [])];
  if (!parts.length) {
    return "Route unavailable.";
  }
  parts = withoutKeys(parts, ["preset", "intent"]);
  const taskArgIndex = Math.min(5, parts.length);
  if (workflow && workflow.preset_id) {
    parts.splice(taskArgIndex, 0, `preset=${workflow.preset_id}`);
  } else if (selected && selected !== "open-ended") {
    parts.splice(taskArgIndex, 0, `intent=${selected}`);
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
  const prior = selectedRuntimeMapPrior(workflow);
  if (prior && workflowSupportsPrior(workflow)) {
    parts = withoutKeys(parts, ["runtime_map_prior"]);
    parts.push(`runtime_map_prior=${prior.path}`);
  }
  return commandPartsWithSetup(parts, workflow).join(" ");
}

export function withProviderProfile(parts, providerProfile) {
  const next = withoutKeys(parts, ["provider_profile"]);
  next.push(`provider_profile=${providerProfile}`);
  return next;
}

export function commandPartsWithSetup(parts, workflow = selectedWorkflow()) {
  const setup = workflow ? workflow.scenario_setup : selectedScenarioSetup();
  const next = withoutKeys(parts, ["scenario_setup", "relocation_count"]);
  next.push(`scenario_setup=${setup}`);
  if (setup !== "baseline") {
    next.push(`relocation_count=${els.relocationCountInput.value || "5"}`);
  }
  return next;
}

export function withoutKeys(parts, keys) {
  return parts.filter((part) => {
    const text = String(part);
    return !keys.some((key) => text.startsWith(`${key}=`));
  });
}

export function renderStartAction(route, readiness) {
  const mode = state.operatorMode;
  const workflow = selectedWorkflow();
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
  els.startButton.textContent = attachableRun
    ? "Attach Existing Run"
    : workflow
    ? workflow.label
    : "Start Agent Run";
  const workflowBlocked = !workflowIsStartable(workflow);
  const workflowHasCatalogRoute = workflowHasRoute(workflow);
  els.startButton.disabled =
    !route.enabled || workflowBlocked || (readiness.can_start === false && !attachableRun);
  const backgroundBlockerText = backgroundBlockerHelp(readiness);
  els.startHelp.textContent = attachableRun
    ? `Existing run ${attachableRun.run_id} is using this backend. Attach to watch it.`
    : !workflowHasCatalogRoute
    ? "This workflow is unavailable for the selected scene/backend."
    : workflowBlocked
    ? (workflow && workflow.disabled_reason) || "This workflow is unavailable for the selected scene/backend."
    : backgroundBlockerText || readiness.blocker || route.unsupported_reason || "";
}

export function backgroundBlockerHelp(readiness) {
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

export function steerHelp(controls) {
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

export function resumeHelp(controls) {
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

export function activeRunHelp(controls) {
  if (controls.operator_handoff_paused) {
    return controls.resume_available
      ? `Paused handoff in ${state.activeRunId}. Use Resume With Prompt after manual control.`
      : `Paused handoff in ${state.activeRunId}. Resume is blocked for this route.`;
  }
  return `Watching active run ${state.activeRunId}. Use Steer.`;
}
