from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from roboclaws.household.manipulation_contract import (
    API_SEMANTIC_PROVENANCE,
    BLOCKED_CAPABILITY_PROVENANCE,
    PLANNER_BACKED_PROVENANCE,
    PLANNER_CLEANUP_PRIMITIVE_TOOLS,
    PLANNER_PRIMITIVE_EXECUTOR_SCHEMA,
    CleanupPrimitiveBackend,
    CleanupPrimitiveRequest,
    CleanupPrimitiveResult,
)


def planner_backed_cleanup_primitive_result(
    *,
    executor: str,
    evidence: Mapping[str, Any],
    status: str = "ok",
    state_mutation: str | None = None,
    tool: str = "",
) -> CleanupPrimitiveResult:
    return CleanupPrimitiveResult(
        ok=True,
        status=status,
        primitive_provenance=PLANNER_BACKED_PROVENANCE,
        planner_backed=True,
        strict_proof_eligible=True,
        executor=executor,
        evidence=dict(evidence),
        state_mutation=state_mutation,
        tool=tool,
    )


def blocked_cleanup_primitive_result(
    *,
    executor: str,
    code: str,
    message: str,
    tool: str = "",
) -> CleanupPrimitiveResult:
    return CleanupPrimitiveResult(
        ok=False,
        status=BLOCKED_CAPABILITY_PROVENANCE,
        primitive_provenance=BLOCKED_CAPABILITY_PROVENANCE,
        planner_backed=False,
        strict_proof_eligible=False,
        executor=executor,
        blockers=({"code": code, "message": message},),
        tool=tool,
    )


class PlannerBackedCleanupContractAdapter:
    """Wrap a cleanup contract with strict per-primitive planner evidence."""

    def __init__(
        self,
        contract: Any,
        *,
        executor: CleanupPrimitiveBackend | None,
        executor_name: str = "planner_cleanup_primitive_executor",
    ) -> None:
        self.contract = contract
        self.executor = executor
        self.executor_name = executor_name
        self.backend = getattr(contract, "backend", None)
        self._current_object_id: str | None = None
        self._held_object_id: str | None = None
        self._source_receptacle_id: str | None = None
        self._target_receptacle_id: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.contract, name)

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        response = self._execute_then_sync(
            tool="navigate_to_object",
            object_id=object_id,
            sync=lambda: self.contract.navigate_to_object(object_id),
        )
        if response.get("ok"):
            self._current_object_id = object_id
            self._source_receptacle_id = _optional_str(
                response.get("source_receptacle_id") or response.get("location_id")
            )
        return response

    def pick(self, object_id: str) -> dict[str, Any]:
        response = self._execute_then_sync(
            tool="pick",
            object_id=object_id,
            source_receptacle_id=self._source_receptacle_id or "",
            sync=lambda: self.contract.pick(object_id),
        )
        if response.get("ok"):
            self._held_object_id = object_id
            self._current_object_id = None
            self._target_receptacle_id = None
            self._source_receptacle_id = _optional_str(
                response.get("previous_location_id") or response.get("source_receptacle_id")
            )
        return response

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        object_id = self._held_object_id or ""
        response = self._execute_then_sync(
            tool="navigate_to_receptacle",
            object_id=object_id,
            target_receptacle_id=receptacle_id,
            source_receptacle_id=self._source_receptacle_id or "",
            sync=lambda: self.contract.navigate_to_receptacle(receptacle_id),
        )
        if response.get("ok"):
            self._target_receptacle_id = receptacle_id
        return response

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._execute_then_sync(
            tool="open_receptacle",
            object_id=self._held_object_id or "",
            target_receptacle_id=receptacle_id,
            source_receptacle_id=self._source_receptacle_id or "",
            sync=lambda: self.contract.open_receptacle(receptacle_id),
        )

    def place(self, receptacle_id: str) -> dict[str, Any]:
        return self._place("place", receptacle_id)

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        return self._place("place_inside", receptacle_id)

    def _place(self, tool: str, receptacle_id: str) -> dict[str, Any]:
        object_id = self._held_object_id or ""
        response = self._execute_then_sync(
            tool=tool,
            object_id=object_id,
            target_receptacle_id=receptacle_id,
            source_receptacle_id=self._source_receptacle_id or "",
            sync=lambda: getattr(self.contract, tool)(receptacle_id),
        )
        if response.get("ok"):
            self._held_object_id = None
            self._target_receptacle_id = None
            self._source_receptacle_id = None
        return response

    def _execute_then_sync(
        self,
        *,
        tool: str,
        sync: Callable[[], dict[str, Any]],
        object_id: str = "",
        target_receptacle_id: str = "",
        source_receptacle_id: str = "",
    ) -> dict[str, Any]:
        request = CleanupPrimitiveRequest(
            tool=tool,
            object_id=object_id,
            target_receptacle_id=target_receptacle_id,
            source_receptacle_id=source_receptacle_id,
            phase_label=tool,
            request=_compact_request(
                object_id=object_id,
                target_receptacle_id=target_receptacle_id,
                source_receptacle_id=source_receptacle_id,
            ),
            context={
                "held_object_id": self._held_object_id or "",
                "current_object_id": self._current_object_id or "",
                "current_target_receptacle_id": self._target_receptacle_id or "",
            },
        )
        if tool != "navigate_to_object" and not object_id:
            primitive_result = blocked_cleanup_primitive_result(
                executor=self.executor_name,
                code="planner_primitive_missing_object_context",
                message=(
                    f"Cleanup primitive executor requires the active object context before {tool}."
                ),
                tool=tool,
            ).to_dict()
            return self._blocked_response(
                request,
                planner_primitive_evidence(request, primitive_result),
                error_reason="planner_primitive_missing_object_context",
            )
        primitive_result = self._call_executor(request)
        planner_evidence = planner_primitive_evidence(request, primitive_result)
        if not _strict_planner_result(request, primitive_result):
            return self._blocked_response(
                request,
                planner_evidence,
                error_reason="planner_primitive_not_backed",
            )

        sync_response = dict(sync())
        if not sync_response.get("ok"):
            return self._sync_failed_response(request, sync_response, planner_evidence)
        return self._planner_backed_response(request, sync_response, planner_evidence)

    def _call_executor(self, request: CleanupPrimitiveRequest) -> dict[str, Any]:
        if self.executor is None:
            return blocked_cleanup_primitive_result(
                executor=self.executor_name,
                code="planner_primitive_executor_unavailable",
                message="No planner-backed cleanup primitive executor was supplied.",
                tool=request.tool,
            ).to_dict()
        try:
            raw_result = self.executor(request)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return blocked_cleanup_primitive_result(
                executor=self.executor_name,
                code="planner_primitive_executor_exception",
                message=f"{type(exc).__name__}: {exc}",
                tool=request.tool,
            ).to_dict()
        if isinstance(raw_result, CleanupPrimitiveResult):
            return raw_result.to_dict()
        if isinstance(raw_result, Mapping):
            result = dict(raw_result)
            result.setdefault("executor", self.executor_name)
            result.setdefault("tool", request.tool)
            return result
        return blocked_cleanup_primitive_result(
            executor=self.executor_name,
            code="planner_primitive_executor_invalid_result",
            message="Executor must return a CleanupPrimitiveResult or mapping.",
            tool=request.tool,
        ).to_dict()

    def _blocked_response(
        self,
        request: CleanupPrimitiveRequest,
        planner_evidence: dict[str, Any],
        *,
        error_reason: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": request.tool,
            "status": BLOCKED_CAPABILITY_PROVENANCE,
            "error_reason": error_reason,
            "object_id": request.object_id or None,
            "receptacle_id": request.target_receptacle_id or None,
            "source_receptacle_id": request.source_receptacle_id or None,
            "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
            "planner_backed": False,
            "strict_proof_eligible": False,
            "state_sync_skipped": True,
            "planner_primitive_evidence": planner_evidence,
            "blockers": list(planner_evidence.get("blockers") or []),
        }

    def _sync_failed_response(
        self,
        request: CleanupPrimitiveRequest,
        sync_response: dict[str, Any],
        planner_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        response = dict(sync_response)
        response.setdefault("tool", request.tool)
        response.setdefault("object_id", request.object_id or None)
        response.setdefault("receptacle_id", request.target_receptacle_id or None)
        response["primitive_provenance"] = BLOCKED_CAPABILITY_PROVENANCE
        response["planner_backed"] = False
        response["strict_proof_eligible"] = False
        response["planner_primitive_evidence"] = planner_evidence
        response["state_sync_provenance"] = sync_response.get(
            "primitive_provenance",
            API_SEMANTIC_PROVENANCE,
        )
        response["state_sync_status"] = sync_response.get("status", "error")
        response.setdefault("error_reason", "state_sync_failed_after_planner_primitive")
        return response

    def _planner_backed_response(
        self,
        request: CleanupPrimitiveRequest,
        sync_response: dict[str, Any],
        planner_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        state_sync_provenance = str(
            sync_response.get("primitive_provenance") or API_SEMANTIC_PROVENANCE
        )
        response = dict(sync_response)
        response.setdefault("tool", request.tool)
        if request.object_id and not response.get("object_id"):
            response["object_id"] = request.object_id
        if request.target_receptacle_id and not response.get("receptacle_id"):
            response["receptacle_id"] = request.target_receptacle_id
        if request.source_receptacle_id and not response.get("source_receptacle_id"):
            response["source_receptacle_id"] = request.source_receptacle_id
        response["primitive_provenance"] = PLANNER_BACKED_PROVENANCE
        response["planner_backed"] = True
        response["strict_proof_eligible"] = True
        response["planner_primitive_evidence"] = {
            **planner_evidence,
            "state_sync_provenance": state_sync_provenance,
            "state_sync_status": sync_response.get("status", "ok"),
            "state_mutation": sync_response.get("state_mutation"),
        }
        response["state_sync_provenance"] = state_sync_provenance
        response["api_semantic_state_sync"] = state_sync_provenance == API_SEMANTIC_PROVENANCE
        response.setdefault("state_mutation", sync_response.get("state_mutation"))
        return response


def planner_primitive_evidence(
    request: CleanupPrimitiveRequest,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = [dict(item) for item in _blockers(result)]
    exact_tool_match = str(result.get("tool") or request.tool) == request.tool
    evidence = _evidence_payload(result)
    if not exact_tool_match:
        blockers.append(
            {
                "code": "planner_primitive_tool_mismatch",
                "message": (
                    f"Executor result tool={result.get('tool')} does not match "
                    f"requested tool={request.tool}."
                ),
            }
        )
    if not evidence:
        blockers.append(
            {
                "code": "planner_primitive_missing_evidence",
                "message": "Planner-backed cleanup primitives require per-call evidence.",
            }
        )
    return {
        "schema": PLANNER_PRIMITIVE_EXECUTOR_SCHEMA,
        "tool": request.tool,
        "object_id": request.object_id,
        "target_receptacle_id": request.target_receptacle_id,
        "source_receptacle_id": request.source_receptacle_id,
        "phase_label": request.phase_label or request.tool,
        "executor": str(result.get("executor") or "unknown"),
        "status": str(result.get("status") or "unknown"),
        "primitive_provenance": str(result.get("primitive_provenance") or "missing"),
        "planner_backed": result.get("planner_backed") is True,
        "strict_proof_eligible": result.get("strict_proof_eligible") is True,
        "exact_tool_match": exact_tool_match,
        "evidence": evidence,
        "request": request.to_dict(),
        "blockers": blockers,
    }


def _strict_planner_result(
    request: CleanupPrimitiveRequest,
    result: Mapping[str, Any],
) -> bool:
    evidence = planner_primitive_evidence(request, result)
    return (
        request.tool in PLANNER_CLEANUP_PRIMITIVE_TOOLS
        and result.get("ok") is True
        and result.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE
        and result.get("planner_backed") is True
        and result.get("strict_proof_eligible") is True
        and evidence["exact_tool_match"] is True
        and bool(evidence["evidence"])
        and not evidence["blockers"]
    )


def _compact_request(
    *,
    object_id: str,
    target_receptacle_id: str,
    source_receptacle_id: str,
) -> dict[str, Any]:
    request = {}
    if object_id:
        request["object_id"] = object_id
    if target_receptacle_id:
        request["receptacle_id"] = target_receptacle_id
    if source_receptacle_id:
        request["source_receptacle_id"] = source_receptacle_id
    return request


def _evidence_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    raw = result.get("evidence") or result.get("planner_primitive_evidence") or {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _blockers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = result.get("blockers") or []
    return [item for item in raw if isinstance(item, Mapping)]


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None and value != "" else None
