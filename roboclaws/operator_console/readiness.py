"""Route readiness gate evaluation helpers for the operator console."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.operator_console.routes import ConsoleLaunchSelection
from roboclaws.operator_console.runtime_inventory import port_owner_task

DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 18788


@dataclass(frozen=True)
class GateEvaluation:
    ok: bool = True
    message: str = "Ready"
    evidence: str = ""
    kind: str = "ready"
    severity: str = "blocking"
    blocks_start: bool = True


def route_gate_rows(
    root: Path,
    route: ConsoleLaunchSelection,
    override_map: dict[str, str],
    gate_map: dict[str, bool],
    provider_status: dict[str, Any],
    runtime_tasks: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str, str]:
    rows: list[dict[str, Any]] = []
    blocker = ""
    blocker_kind = ""
    for gate in route.gates:
        evaluation = _evaluate_route_gate(
            root, route, gate, override_map, gate_map, provider_status, runtime_tasks
        )
        if not evaluation.ok and evaluation.blocks_start and not blocker:
            blocker = evaluation.message
            blocker_kind = evaluation.kind
        rows.append(_route_gate_payload(gate, evaluation))
    return rows, blocker, blocker_kind


def _evaluate_route_gate(
    root: Path,
    route: ConsoleLaunchSelection,
    gate: Any,
    override_map: dict[str, str],
    gate_map: dict[str, bool],
    provider_status: dict[str, Any],
    runtime_tasks: list[dict[str, Any]] | None,
) -> GateEvaluation:
    evaluator = _GATE_EVALUATORS.get(gate.kind)
    if evaluator is None:
        return GateEvaluation(severity=gate.severity, blocks_start=gate.required)
    return evaluator(root, route, gate, override_map, gate_map, provider_status, runtime_tasks)


def _provider_key_gate(
    root: Path,
    route: ConsoleLaunchSelection,
    gate: Any,
    override_map: dict[str, str],
    gate_map: dict[str, bool],
    provider_status: dict[str, Any],
    runtime_tasks: list[dict[str, Any]] | None,
) -> GateEvaluation:
    del root, override_map, gate_map, runtime_tasks
    if not provider_status["ok"]:
        label = route.to_payload().get("agent_engine_label") or route.agent_engine_id
        return GateEvaluation(
            ok=False,
            message=str(provider_status["message"] or f"No {label} provider route found."),
            kind="needs_provider",
            severity=gate.severity,
            blocks_start=gate.required,
        )
    if provider_status.get("capability_blocker"):
        return GateEvaluation(
            ok=False,
            message=str(provider_status["capability_blocker"]),
            kind="unsupported_evidence_lane",
            severity=gate.severity,
            blocks_start=gate.required,
        )
    return GateEvaluation(severity=gate.severity, blocks_start=gate.required)


def _mcp_port_gate(
    root: Path,
    route: ConsoleLaunchSelection,
    gate: Any,
    override_map: dict[str, str],
    gate_map: dict[str, bool],
    provider_status: dict[str, Any],
    runtime_tasks: list[dict[str, Any]] | None,
) -> GateEvaluation:
    del root, route, gate_map, provider_status
    host = _override_host(override_map)
    port = _override_port(override_map)
    evidence = f"{host}:{port}"
    if _tcp_port_free(host, port):
        return GateEvaluation(evidence=evidence, severity=gate.severity, blocks_start=gate.required)
    owner = port_owner_task(runtime_tasks or [], host=host, port=port)
    owner_text = ""
    if owner:
        owner_text = f" Owner: {owner.get('label') or owner.get('id')}."
    return GateEvaluation(
        ok=False,
        message=(
            f"MCP port {host}:{port} is already accepting connections. "
            "Pick another port or stop the existing server."
            f"{owner_text}"
        ),
        evidence=evidence,
        kind="mcp_port_in_use",
        severity=gate.severity,
        blocks_start=gate.required,
    )


def _request_field_gate(
    root: Path,
    route: ConsoleLaunchSelection,
    gate: Any,
    override_map: dict[str, str],
    gate_map: dict[str, bool],
    provider_status: dict[str, Any],
    runtime_tasks: list[dict[str, Any]] | None,
) -> GateEvaluation:
    del gate_map, provider_status, runtime_tasks
    raw_override = str(override_map.get(gate.id) or "").strip()
    raw_path = raw_override or _route_default_override(route, gate.id).strip()
    kind = _request_field_kind(gate.id)
    label = str(getattr(gate, "label", None) or gate.id)
    if not raw_path:
        return GateEvaluation(
            ok=False,
            message=str(getattr(gate, "help_text", None) or f"Attach {label}."),
            kind=kind,
            severity=gate.severity,
            blocks_start=gate.required,
        )
    context_path = Path(raw_path).expanduser()
    if not context_path.is_absolute():
        context_path = root / context_path
    if not context_path.is_file():
        return GateEvaluation(
            ok=False,
            message=f"{label} was not found: {raw_path}",
            kind=kind,
            severity=gate.severity,
            blocks_start=gate.required,
        )
    try:
        payload = read_json_object(context_path, label=label)
    except ValueError as exc:
        if exc.__cause__ is None:
            return GateEvaluation(
                ok=False,
                message=f"{label} must contain a JSON object: {raw_path}",
                kind=kind,
                severity=gate.severity,
                blocks_start=gate.required,
            )
        return GateEvaluation(
            ok=False,
            message=f"{label} is not readable JSON: {raw_path} ({exc})",
            kind=kind,
            severity=gate.severity,
            blocks_start=gate.required,
        )
    except OSError as exc:
        return GateEvaluation(
            ok=False,
            message=f"{label} is not readable JSON: {raw_path} ({exc})",
            kind=kind,
            severity=gate.severity,
            blocks_start=gate.required,
        )
    return GateEvaluation(
        evidence=str(context_path),
        severity=gate.severity,
        blocks_start=gate.required,
    )


def _request_field_kind(gate_id: str) -> str:
    if gate_id == "context_json":
        return "needs_agibot_context"
    return "needs_route_parameter"


def _route_default_override(route: ConsoleLaunchSelection, key: str) -> str:
    prefix = f"{key}="
    for item in route.launch_default_overrides:
        if item.startswith(prefix):
            return item[len(prefix) :]
    return ""


def _operator_gate(
    root: Path,
    route: ConsoleLaunchSelection,
    gate: Any,
    override_map: dict[str, str],
    gate_map: dict[str, bool],
    provider_status: dict[str, Any],
    runtime_tasks: list[dict[str, Any]] | None,
) -> GateEvaluation:
    del root, route, provider_status, runtime_tasks
    real_movement_enabled = _truthy_override(override_map.get("real_movement_enabled"))
    blocks_start = real_movement_enabled
    if gate_map.get(gate.id) is True:
        return GateEvaluation(severity=gate.severity, blocks_start=blocks_start)
    if real_movement_enabled:
        return GateEvaluation(
            ok=False,
            message=(
                "Real movement is enabled; localization, run enablement, "
                "and E-stop/manual-stop readiness must be accepted before launch."
            ),
            kind="needs_real_movement_gate",
            severity=gate.severity,
            blocks_start=blocks_start,
        )
    return GateEvaluation(
        ok=False,
        message="Dry-run launch can start; this evidence is required for real movement.",
        kind="real_movement_gate_pending",
        severity=gate.severity,
        blocks_start=blocks_start,
    )


def _route_gate_payload(gate: Any, evaluation: GateEvaluation) -> dict[str, Any]:
    return {
        "id": gate.id,
        "label": gate.label,
        "status": "ready" if evaluation.ok else "needs_action",
        "kind": "ready" if evaluation.ok else evaluation.kind,
        "severity": evaluation.severity,
        "required": evaluation.blocks_start,
        "blocks_start": evaluation.blocks_start,
        "message": evaluation.message,
        "evidence": evaluation.evidence,
        "help_text": gate.help_text,
    }


def _override_host(overrides: dict[str, str]) -> str:
    host = str(overrides.get("host") or DEFAULT_MCP_HOST).strip()
    return host or DEFAULT_MCP_HOST


def _override_port(overrides: dict[str, str]) -> int:
    return _parse_port(str(overrides.get("port") or DEFAULT_MCP_PORT))


def _parse_port(value: str) -> int:
    try:
        port = int(str(value).strip())
    except ValueError as exc:
        raise _console_launch_error(f"invalid MCP port: {value}") from exc
    if not 1 <= port <= 65535:
        raise _console_launch_error(f"invalid MCP port: {value}")
    return port


_GATE_EVALUATORS: dict[str, Any] = {
    "provider_key": _provider_key_gate,
    "mcp_port_free": _mcp_port_gate,
    "request_field": _request_field_gate,
    "operator_gate": _operator_gate,
}


def _console_launch_error(message: str) -> ValueError:
    from roboclaws.operator_console.launcher import ConsoleLaunchError

    return ConsoleLaunchError(message)


def _truthy_override(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _tcp_port_free(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.2):
            return False
    except OSError:
        return True
