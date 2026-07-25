from __future__ import annotations

import json
import os
import time
from typing import Any

from roboclaws.core.provider_runtime import (
    _COST_PER_M,
    _SYSTEM_PROMPT,
    ProviderStatus,
    _build_agent_action_model,
    _record_call_failure,
    _record_call_success,
    action_decision_from_fields,
)

_IMPORT_ERROR = "openai and instructor packages required: pip install openai instructor"


class _OpenAIBase:
    def _init_provider(
        self,
        *,
        provider_name: str,
        model: str,
        api_key_env: str,
        api_key: str | None,
        max_tokens: int,
        base_url: str | None = None,
        use_instructor: bool = True,
    ) -> Any:
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(_IMPORT_ERROR) from exc

        client_kwargs = {"api_key": api_key or os.environ[api_key_env]}
        if base_url:
            client_kwargs["base_url"] = base_url
        raw_client = OpenAI(**client_kwargs)

        self._AgentAction = _build_agent_action_model()
        if use_instructor:
            try:
                import instructor
            except ImportError as exc:
                raise ImportError(_IMPORT_ERROR) from exc
            self._client = instructor.from_openai(raw_client)
        else:
            self._client = raw_client

        self.model = model
        self._max_tokens = max_tokens
        self._cost = 0.0
        self._cost_table = _COST_PER_M.get(model, {"input": 0.0, "output": 0.0})
        self._status = ProviderStatus(provider_name=provider_name, model=model)
        return raw_client

    @property
    def cumulative_cost(self) -> float:
        return self._cost

    def reset_cost(self) -> None:
        self._cost = 0.0

    def get_status(self) -> dict[str, Any]:
        return self._status.to_dict()

    def _build_messages(self, images: list[str], state: dict[str, Any]) -> list[dict[str, Any]]:
        content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "low"},
            }
            for img_b64 in images
        ]
        content.append({"type": "text", "text": json.dumps(state, indent=2)})
        return [{"role": "user", "content": content}]

    def _messages_with_system(
        self, images: list[str], state: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [{"role": "system", "content": _SYSTEM_PROMPT}, *self._build_messages(images, state)]

    def _record_usage(self, usage: Any) -> None:
        if not usage:
            return
        self._cost += (
            int(getattr(usage, "prompt_tokens", 0) or 0) / 1_000_000 * self._cost_table["input"]
            + int(getattr(usage, "completion_tokens", 0) or 0)
            / 1_000_000
            * self._cost_table["output"]
        )


class OpenAIProvider(_OpenAIBase):
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        max_tokens: int = 256,
    ) -> None:
        self._init_provider(
            provider_name="openai",
            model=model,
            api_key_env="OPENAI_API_KEY",
            api_key=api_key,
            max_tokens=max_tokens,
        )

    def get_action(
        self,
        images: list[str],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result, response = self._client.chat.completions.create_with_completion(
                model=self.model,
                messages=self._messages_with_system(images, state),  # type: ignore[arg-type]
                max_tokens=self._max_tokens,
                response_model=self._AgentAction,
            )
        except Exception as exc:
            _record_call_failure(
                self._status,
                duration_seconds=time.monotonic() - started,
                error=exc,
            )
            raise

        _record_call_success(self._status, duration_seconds=time.monotonic() - started)
        self._record_usage(response.usage)
        return action_decision_from_fields(result.reasoning, result.action).to_dict()
