import { els, state } from "./state.js";
import {
  refreshRuntimeTasks,
  renderBackgroundTaskButton,
} from "./background-tasks.js";
import { fetchJson } from "./http-dom.js";
import {
  attachLatestResult,
  confirmAction,
  handleStartAction,
  refreshPromptPreview,
  refreshSelectedRouteReadiness,
  scheduleReadinessRefresh,
} from "./launch.js";
import { postManualControl } from "./manual-control.js";
import { postRunAction, toggleRawEvidence } from "./run-session.js";
import { copyVisualPath, renderViewModes } from "./visual-workspace.js";
import {
  combinationsForWorld,
  orderedVisibleWorlds,
  preferredDefaultCombination,
  preferredPreviewCombination,
  preferredWorkflowForWorld,
  routeForWorkflow,
  selectedIntent,
  selectedWorkflow,
} from "./workflow-model.js";
import { renderRoutes, renderSelection } from "./workflow-view.js";

async function boot() {
  const payload = await fetchJson("/api/routes");
  state.evidenceLanes = payload.evidence_lanes || [];
  state.workflows = payload.workflows || [];
  state.recommendedPriors = payload.recommended_priors || [];
  state.combinations = payload.combinations || [];
  state.worlds = orderedVisibleWorlds(payload.worlds || []);
  state.readiness = payload.readiness || {};
  state.runtime = payload.runtime || { tasks: [], summary: {} };
  state.selectedWorld = state.worlds[0] || null;
  state.selectedWorkflow = preferredWorkflowForWorld(state.selectedWorld);
  state.selectedRoute =
    routeForWorkflow(state.selectedWorkflow, state.selectedWorld) ||
    preferredPreviewCombination(combinationsForWorld(state.selectedWorld && state.selectedWorld.id)) ||
    preferredDefaultCombination(combinationsForWorld(state.selectedWorld && state.selectedWorld.id)) ||
    preferredDefaultCombination(state.combinations) ||
    state.combinations[0];
  if (state.selectedRoute) {
    state.selectedWorld =
      state.worlds.find((world) => world.id === state.selectedRoute.world_id) || state.selectedWorld;
    state.selectedIntent = state.selectedRoute.intent_id || "";
    state.selectedWorkflow = preferredWorkflowForWorld(state.selectedWorld);
    state.syncAxesFromRoute = true;
  }
  renderRoutes();
  renderSelection();
  renderBackgroundTaskButton();
  bindEvents();
  renderViewModes();
}

function bindEvents() {
  bindLaunchFormEvents();
  bindRunActionEvents();
  bindWorkspaceEvents();
}

function bindLaunchFormEvents() {
  bindPromptEvents();
  bindAxisEvents();
  bindScenarioEvents();
  bindLaunchActionEvents();
}

function bindPromptEvents() {
  els.taskPrompt.addEventListener("input", () => {
    els.promptCount.textContent = `${els.taskPrompt.value.length} / 2000`;
    renderSelection();
  });
  els.intentInput.addEventListener("change", () => {
    state.selectedIntent = els.intentInput.value;
    renderSelection();
  });
}

function bindAxisEvents() {
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
  els.runtimeMapPriorInput.addEventListener("input", () => {
    renderSelection();
    renderRoutes();
  });
  els.runtimeMapPriorInput.addEventListener("change", () => {
    renderSelection();
    refreshSelectedRouteReadiness();
  });
}

function bindScenarioEvents() {
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
}

function bindLaunchActionEvents() {
  els.startButton.addEventListener("click", handleStartAction);
  els.promptPreviewButton.addEventListener("click", refreshPromptPreview);
  els.latestResultButton.addEventListener("click", attachLatestResult);
  els.backgroundTasksButton.addEventListener("click", refreshRuntimeTasks);
}

function bindRunActionEvents() {
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
}

function bindWorkspaceEvents() {
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

boot();
