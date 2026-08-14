import { state, els, DEFAULT_UI_INTENT, DEFAULT_WORKFLOW_ID } from "./state.js";

export function orderedVisibleWorlds(worlds) {
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

export function isMolmospacesWorld(world) {
  return world.id.startsWith("molmospaces/") || (world.tags || []).includes("molmospaces");
}

export function combinationsForWorld(worldId) {
  return state.combinations.filter((item) => item.world_id === worldId);
}

export function preferredDefaultCombination(combinations) {
  return (
    combinations.find(
      (item) =>
        item.enabled &&
        item.intent_id === DEFAULT_UI_INTENT &&
        item.evidence_lane === "camera-grounded-labels" &&
        item.agent_engine_id === "openai-agents-sdk"
    ) ||
    combinations.find((item) => item.enabled && item.intent_id === DEFAULT_UI_INTENT) ||
    combinations.find((item) => item.enabled) ||
    combinations[0]
  );
}

export function preferredPreviewCombination(combinations) {
  return preferredDefaultCombination(combinations.filter(routeHasPreviewAssets));
}

export function routeHasPreviewAssets(route) {
  return Boolean(route && route.preview_assets && Object.keys(route.preview_assets).length);
}

export function preferredWorkflowForWorld(world = state.selectedWorld) {
  const workflows = workflowActionsForWorld(world);
  return (
    workflows.find((item) => item.id === DEFAULT_WORKFLOW_ID && item.enabled) ||
    workflows.find((item) => item.enabled) ||
    workflows[0] ||
    null
  );
}

export function workflowActionsForWorld(world = state.selectedWorld) {
  if (!world) {
    return state.workflows || [];
  }
  return world.workflow_actions || state.workflows || [];
}

export function selectedWorkflow() {
  const workflows = workflowActionsForWorld();
  if (!state.selectedWorkflow || !workflows.some((item) => item.id === state.selectedWorkflow.id)) {
    state.selectedWorkflow = preferredWorkflowForWorld();
  }
  return state.selectedWorkflow;
}

export function routeForWorkflow(workflow = selectedWorkflow(), world = state.selectedWorld) {
  if (!workflow) {
    return null;
  }
  if (workflow.default_route_id) {
    const exact = state.combinations.find((item) => item.id === workflow.default_route_id);
    if (exact) {
      return exact;
    }
  }
  const worldId = world && world.id;
  return (
    combinationsForWorld(worldId).find(
      (item) =>
        item.enabled &&
        item.intent_id === workflowIntent(workflow) &&
        item.evidence_lane === (workflow.default_evidence_lane || "camera-grounded-labels") &&
        item.agent_engine_id === "openai-agents-sdk"
    ) || null
  );
}

export function workflowForRoute(route) {
  if (!route) {
    return preferredWorkflowForWorld();
  }
  const workflows = workflowActionsForWorld(
    state.worlds.find((world) => world.id === route.world_id) || state.selectedWorld
  );
  return (
    workflows.find((workflow) => workflow.intent_id === route.intent_id) ||
    preferredWorkflowForWorld()
  );
}

export function workflowIntent(workflow) {
  return (workflow && workflow.intent_id) || "";
}

export function workflowSupportsPrior(workflow = selectedWorkflow()) {
  return Boolean(workflow && workflow.allows_prior_override);
}

export function workflowHasRoute(workflow = selectedWorkflow()) {
  return Boolean(routeForWorkflow(workflow));
}

export function selectedRuntimeMapPrior(workflow = selectedWorkflow()) {
  if (!workflowSupportsPrior(workflow)) {
    return null;
  }
  const override = els.runtimeMapPriorInput.value.trim();
  if (override) {
    return { path: override, source: "operator_override", status: "operator-selected" };
  }
  return workflow && workflow.recommended_prior ? workflow.recommended_prior : null;
}

export function workflowIsStartable(workflow = selectedWorkflow()) {
  if (!workflow || !workflowHasRoute(workflow)) {
    return false;
  }
  if (workflow.enabled === false) {
    return false;
  }
  return true;
}

export function selectedCombinationFromAxes() {
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

export function currentSelectValue(select, options, fallbackValue = "") {
  const current = select.value || "";
  if (current && options.some((option) => option.value === current)) {
    return current;
  }
  if (fallbackValue && options.some((option) => option.value === fallbackValue)) {
    return fallbackValue;
  }
  return current || fallbackValue || "";
}

export function uniqueOptions(items, valueKey, labelKey, labelFn) {
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

export function intentOptionsForCurrentAxes(combos) {
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

export function evidenceLaneOptions(combos) {
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

export function defaultScenarioSetup(route, intent, defaults) {
  const workflow = selectedWorkflow();
  if (workflow && workflow.scenario_setup) {
    return workflow.scenario_setup;
  }
  if (intent === "cleanup") {
    return route.scenario_setup || defaults.scenario_setup || "relocate-cleanup-related-objects";
  }
  return "baseline";
}

export function selectedScenarioSetup() {
  const workflow = selectedWorkflow();
  if (workflow && workflow.scenario_setup) {
    return workflow.scenario_setup;
  }
  return els.scenarioSetupInput.value || "baseline";
}

export function routeDefaultOverrides(route) {
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

export function launchPromptText() {
  if (state.operatorMode !== "goal" || state.activeRunId) {
    return "";
  }
  return els.taskPrompt.value.trim();
}

export function effectiveLaunchPromptText(route = state.selectedRoute) {
  const prompt = launchPromptText();
  if (prompt) {
    return prompt;
  }
  if (route && selectedIntentForRoute(route) === "open-ended") {
    return route.task_prompt_default || route.default_prompt || "";
  }
  return "";
}

export function selectedIntent() {
  const workflow = selectedWorkflow();
  if (workflowIntent(workflow)) {
    return workflowIntent(workflow);
  }
  const route = state.selectedRoute;
  if (!route) {
    return "";
  }
  const value = els.intentInput.value || state.selectedIntent || route.intent_id;
  return selectedIntentForRoute(route, value);
}

export function selectedIntentForRoute(route, requestedIntent = "") {
  const options = intentOptions(route);
  const fallback = route.intent_id || (options[0] && options[0].id) || "";
  const candidate = requestedIntent || state.selectedIntent || fallback;
  return options.some((option) => option.id === candidate) ? candidate : fallback;
}

export function intentOptions(route) {
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

export function launchInterpretation(route) {
  const workflow = selectedWorkflow();
  const intent = workflowIntent(workflow) || selectedIntentForRoute(route);
  const option = intentOptions(route).find((item) => item.id === intent) || {};
  return {
    intent,
    intentLabel: option.label || intentLabel(intent),
    goalScope: goalScopeForIntent(intent, option.goal_scope || ""),
    checker: option.checker_id || route.checker_id || "",
    evaluation: option.evaluation_policy || intent.replace("-", "_"),
  };
}

export function goalScopeForIntent(intent, defaultScope) {
  if (intent === "cleanup") {
    return launchPromptText() ? "prompt-scoped" : "whole-room";
  }
  if (intent === "map-build") {
    return "whole-room";
  }
  return defaultScope || "agent-declared";
}

export function intentLabel(intent) {
  const labels = {
    cleanup: "Cleanup",
    "open-ended": "Open-ended",
    "map-build": "Map build",
  };
  return labels[intent] || intent;
}

export function effectiveReadiness(route) {
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

export function applyLocalGateEvidence(gate) {
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

export function firstBlockingGateKind(gates) {
  const gate = gates.find((item) => item.status !== "ready" && gateBlocksStart(item));
  return gate ? gate.kind || "" : "";
}

export function gateBlocksStart(gate) {
  return Boolean(gate.blocks_start || gate.required);
}

export function isRunTerminal(payload = state.activeState || {}) {
  if (!state.activeRunId) {
    return false;
  }
  const controls = payload.controls || {};
  return controls.next_goal_available === true;
}

export function isRealMovementGate(gate) {
  return ["localization_ready", "run_enabled", "estop_ready"].includes(gate.id);
}

export function isAgibotRoute(route) {
  const groups = new Set((route && route.field_groups) || []);
  return Boolean(route && (route.backend_id === "agibot-gdk" || groups.has("agibot_gates")));
}

export function selectedProviderProfile() {
  return (els.providerProfileInput && els.providerProfileInput.value) || "";
}

export function selectedProviderRoute(route = state.selectedRoute) {
  const providerProfile = selectedProviderProfile();
  if (!providerProfile || !route || !Array.isArray(route.provider_routes)) {
    return null;
  }
  return route.provider_routes.find((item) => item.provider_profile === providerProfile) || null;
}

export function selectedProviderLabel(route = state.selectedRoute) {
  const providerRoute = selectedProviderRoute(route);
  return providerRoute ? providerRoute.label : selectedProviderProfile();
}

export function providerProfileLabel(profile, route = state.selectedRoute) {
  if (!route || !Array.isArray(route.provider_routes)) {
    return profile;
  }
  const providerRoute = route.provider_routes.find((item) => item.provider_profile === profile);
  return providerRoute ? providerRoute.label : profile;
}
