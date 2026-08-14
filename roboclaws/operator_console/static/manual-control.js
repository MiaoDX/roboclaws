import { state, els, MANUAL_CONTROL_STEP_M, MANUAL_CONTROL_TURN_DEG } from "./state.js";
import { fetchJson } from "./http-dom.js";
import { pollState } from "./run-session.js";

export function renderManualControl(payload = state.activeState || {}) {
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

export function manualControlStatusText(payload, controls, available) {
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
    if (controls.relative_navigation_control_pending) {
      return "Manual control is waiting for the MCP endpoint to become ready.";
    }
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

export function relativeDeltaText(delta) {
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

export function formatSigned(value) {
  return `${value > 0 ? "+" : ""}${Number(value).toFixed(Math.abs(value) < 1 ? 2 : 1)}`;
}

export async function postManualControl(action) {
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

export function manualControlPayload(action) {
  const byAction = {
    forward: [MANUAL_CONTROL_STEP_M, 0, 0],
    back: [-MANUAL_CONTROL_STEP_M, 0, 0],
    left: [0, MANUAL_CONTROL_STEP_M, 0],
    right: [0, -MANUAL_CONTROL_STEP_M, 0],
    "turn-left": [0, 0, MANUAL_CONTROL_TURN_DEG],
    "turn-right": [0, 0, -MANUAL_CONTROL_TURN_DEG],
  };
  if (action === "observe") {
    return { action: "observe" };
  }
  const delta = byAction[action];
  return delta
    ? {
        action: "navigate_to_relative_pose",
        forward_m: delta[0],
        lateral_m: delta[1],
        yaw_delta_deg: delta[2],
      }
    : null;
}

export function manualControlResultText(result) {
  const response = result.response || {};
  if (response.applied_delta) {
    return `Operator move recorded: ${relativeDeltaText(response.applied_delta)}.`;
  }
  if (result.action === "observe") {
    return "Operator observe recorded.";
  }
  return `Operator control recorded: ${result.action || "control"}.`;
}

export function operatorMessageResultText(result) {
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
