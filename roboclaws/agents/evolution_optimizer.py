"""Narrow OpenAI Agents SDK optimizer adapter for Eval Evolution."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from roboclaws.agents import provider_transport
from roboclaws.agents.drivers.openai_agents_event_projection import _usage_summary
from roboclaws.agents.provider_registry import openai_agents_runtime_settings

OPTIMIZER_TOOL_NAMES = (
    "read_evolution_target",
    "read_evolution_feedback",
    "submit_evolution_candidate",
)


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CandidateSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: str
    patch: str


@dataclass(frozen=True)
class OptimizerOutcome:
    hypothesis: str
    patch: str
    identity: dict[str, Any]
    usage: dict[str, Any]
    trace_id: str


def optimizer_tool_surface_digest() -> str:
    encoded = json.dumps(OPTIMIZER_TOOL_NAMES, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def build_optimizer_tools(
    *,
    target: dict[str, Any],
    feedback: Any,
    submit: Callable[[str, str], None],
    function_tool_cls: Any | None = None,
) -> list[Any]:
    _validate_optimizer_visible_payload(target)
    feedback_payload = feedback.to_dict()
    _validate_optimizer_visible_payload(feedback_payload)
    if function_tool_cls is None:
        from agents.tool import FunctionTool  # type: ignore[import-not-found]

        function_tool_cls = FunctionTool

    async def read_target(_context: Any, raw_input: str) -> dict[str, Any]:
        _NoArguments.model_validate_json(raw_input)
        return dict(target)

    async def read_feedback(_context: Any, raw_input: str) -> dict[str, Any]:
        _NoArguments.model_validate_json(raw_input)
        return dict(feedback_payload)

    async def submit_candidate(_context: Any, raw_input: str) -> dict[str, Any]:
        proposal = _CandidateSubmission.model_validate_json(raw_input)
        if not proposal.hypothesis.strip() or not proposal.patch.strip():
            return {
                "accepted_for_host_validation": False,
                "error": "candidate hypothesis and patch must be non-empty",
            }
        relative_path = str(target.get("relative_path") or "")
        try:
            _validate_submitted_patch(proposal.patch, relative_path=relative_path)
            _validate_patch_applicability(
                proposal.patch,
                relative_path=relative_path,
                target_content=str(target.get("content") or ""),
            )
        except ValueError as exc:
            return {
                "accepted_for_host_validation": False,
                "error": str(exc),
            }
        submit(proposal.hypothesis, proposal.patch)
        return {
            "accepted_for_host_validation": True,
            "patch_sha256": sha256(proposal.patch.encode("utf-8")).hexdigest(),
        }

    return [
        function_tool_cls(
            name="read_evolution_target",
            description="Read the one declared public evolution target. No path is accepted.",
            params_json_schema=_NoArguments.model_json_schema(),
            on_invoke_tool=read_target,
            strict_json_schema=True,
        ),
        function_tool_cls(
            name="read_evolution_feedback",
            description="Read the current sanitized eval feedback packet.",
            params_json_schema=_NoArguments.model_json_schema(),
            on_invoke_tool=read_feedback,
            strict_json_schema=True,
        ),
        function_tool_cls(
            name="submit_evolution_candidate",
            description="Submit one hypothesis and unified text patch for host validation.",
            params_json_schema=_CandidateSubmission.model_json_schema(),
            on_invoke_tool=submit_candidate,
            strict_json_schema=True,
        ),
    ]


def run_optimizer_agent(
    campaign: Any,
    *,
    target: dict[str, Any],
    feedback: Any,
    run_dir: Path,
) -> OptimizerOutcome:
    from agents import (  # type: ignore[import-not-found]
        Agent,
        ModelSettings,
        OpenAIChatCompletionsModel,
        OpenAIResponsesModel,
        RunConfig,
        Runner,
    )
    from openai import AsyncOpenAI  # type: ignore[import-not-found]

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    proposal: dict[str, str] = {}

    def submit(hypothesis: str, patch: str) -> None:
        if proposal:
            raise ValueError("optimizer may submit exactly one candidate per turn")
        proposal.update(hypothesis=hypothesis, patch=patch)

    tools = build_optimizer_tools(target=target, feedback=feedback, submit=submit)
    optimizer = campaign.optimizer
    settings = openai_agents_runtime_settings(
        provider_profile=str(optimizer["provider_profile"]),
        request_provider_profile=str(optimizer["provider_profile"]),
        model=str(optimizer["model"]),
        request_model=str(optimizer["model"]),
        base_url=None,
        api_key=None,
    )
    client = AsyncOpenAI(
        api_key=settings["api_key"],
        base_url=settings["base_url"],
        **provider_transport.provider_client_options(settings["provider_profile"], run_dir),
    )
    model = _provider_model(
        settings,
        client=client,
        responses_model_cls=OpenAIResponsesModel,
        chat_model_cls=OpenAIChatCompletionsModel,
    )
    configured_settings = provider_transport.compatible_model_settings(
        settings["provider_profile"], dict(optimizer.get("settings") or {})
    )
    configured_settings.update(tool_choice="auto", parallel_tool_calls=False)
    model_settings = ModelSettings(**configured_settings)
    agent = Agent(
        name=f"roboclaws-eval-evolution-optimizer-{campaign.campaign_id}",
        instructions=(
            "Propose one bounded improvement to the declared target. Read the target and "
            "sanitized feedback with the provided tools, then submit exactly one hypothesis "
            "and a raw unified git diff. The diff must begin with `diff --git a/<relative_path> "
            "b/<relative_path>`, include matching `---` and `+++` headers, contain exact hunk "
            "line counts, end with a newline, and apply to the target content verbatim. Do not "
            "wrap it in Markdown or use apply_patch markers. If submission returns "
            "accepted_for_host_validation=false, correct the reported format/applicability "
            "error and resubmit. You cannot launch evals or inspect any other data."
        ),
        model=model,
        model_settings=model_settings,
        tools=tools,
    )
    run_config = RunConfig(
        trace_include_sensitive_data=False,
        workflow_name="roboclaws-eval-evolution-optimizer",
        trace_metadata={
            "campaign_id": campaign.campaign_id,
            "role": "optimizer",
            "provider_profile": settings["provider_profile"],
        },
    )

    async def run_with_timeout() -> Any:
        try:
            return await asyncio.wait_for(
                Runner.run(
                    agent,
                    "Read the bounded inputs and submit one candidate.",
                    max_turns=_sdk_turn_budget(campaign),
                    run_config=run_config,
                ),
                timeout=float(campaign.budgets["timeout_s"]),
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("optimizer provider call exceeded campaign timeout_s") from exc
        finally:
            await client.close()

    result = asyncio.run(run_with_timeout())
    if not proposal:
        raise ValueError("optimizer completed without submitting a candidate")
    return OptimizerOutcome(
        hypothesis=proposal["hypothesis"],
        patch=proposal["patch"],
        identity={
            "role": "optimizer",
            "agent_engine": "openai-agents-sdk",
            "provider_profile": settings["provider_profile"],
            "model": settings["request_model"],
            "agents_sdk_version": _sdk_version(),
            "tool_surface_sha256": optimizer_tool_surface_digest(),
        },
        usage=_usage_summary(result),
        trace_id=str(getattr(result, "trace_id", "") or ""),
    )


def _provider_model(
    settings: dict[str, str],
    *,
    client: Any,
    responses_model_cls: Any,
    chat_model_cls: Any,
) -> Any:
    if settings["wire_api"] == "responses":
        return responses_model_cls(settings["request_model"], openai_client=client)
    if settings["wire_api"] == "chat-completions":
        return chat_model_cls(settings["request_model"], openai_client=client)
    raise ValueError(f"unsupported OpenAI Agents wire API: {settings['wire_api']}")


def _sdk_version() -> str:
    try:
        return importlib.metadata.version("openai-agents")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _sdk_turn_budget(campaign: Any) -> int:
    # Reads and the final result consume transport turns in addition to each
    # campaign-authorized proposal/revision turn. This does not grant another candidate.
    return 4 + int(campaign.budgets["optimizer_turns"]) * 4


def _validate_submitted_patch(patch: str, *, relative_path: str) -> None:
    if not relative_path:
        raise ValueError("optimizer target is missing its authorized relative_path")
    expected_header = f"diff --git a/{relative_path} b/{relative_path}\n"
    if not patch.startswith(expected_header):
        raise ValueError(
            "patch must be a raw unified git diff beginning with "
            f"{expected_header.strip()!r}; do not use Markdown fences or apply_patch markers"
        )
    if not patch.endswith("\n"):
        raise ValueError("patch must end with a newline")
    lines = patch.splitlines()
    diff_headers = [line for line in lines if line.startswith("diff --git ")]
    if not diff_headers or any(line != expected_header.rstrip("\n") for line in diff_headers):
        raise ValueError("patch may modify only the authorized relative_path")
    expected_old = f"--- a/{relative_path}"
    expected_new = f"+++ b/{relative_path}"
    if expected_old not in lines or expected_new not in lines:
        raise ValueError("patch must contain authorized --- and +++ file headers")
    if not any(line.startswith("@@ ") for line in lines):
        raise ValueError("patch must contain at least one unified diff hunk")


def _validate_patch_applicability(patch: str, *, relative_path: str, target_content: str) -> None:
    with tempfile.TemporaryDirectory(prefix="roboclaws-evolution-patch-") as raw_root:
        root = Path(raw_root)
        target_path = root / relative_path
        target_path.parent.mkdir(parents=True)
        target_path.write_text(target_content, encoding="utf-8")
        env = dict(os.environ)
        env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
        result = subprocess.run(
            ["git", "apply", "--no-index", "--check", "--whitespace=error-all"],
            cwd=root,
            env=env,
            input=patch.encode("utf-8"),
            capture_output=True,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"patch does not apply to the declared target: {detail}")


def _validate_optimizer_visible_payload(payload: Any, *, path: str = "$") -> None:
    forbidden = {
        "acceptable_destination",
        "api_key",
        "credential",
        "endpoint",
        "generated_mess",
        "grader_config",
        "grader_internal",
        "holdout",
        "private_goal",
        "private_truth",
        "provider_key",
        "raw_provider",
        "selection_threshold",
        "scenario_secret",
        "secret",
        "token_value",
    }
    host_path = re.compile(r"(?:^|\s)/(?:home|root|Users|workspace|workspaces|mnt)/\S+")
    proc_path = re.compile(r"(?:^|\s)/proc(?:/|\s|$)")
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = "".join(char.lower() if char.isalnum() else "_" for char in str(key))
            if normalized in forbidden:
                raise ValueError(
                    f"optimizer-visible payload contains forbidden key at {path}.{key}"
                )
            _validate_optimizer_visible_payload(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _validate_optimizer_visible_payload(value, path=f"{path}[{index}]")
    elif isinstance(payload, str) and (host_path.search(payload) or proc_path.search(payload)):
        raise ValueError(f"optimizer-visible payload contains host path at {path}")
