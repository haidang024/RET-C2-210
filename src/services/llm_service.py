"""LLM adapter for the framework's injected provider-neutral client."""

from __future__ import annotations

from typing import Any

from src.services.llm_runtime import complete_text


class LLMService:
    """Translate domain prompts to the canonical BaseLLM.complete contract."""

    def __init__(self, client: Any = None, config: dict[str, Any] | None = None) -> None:
        self._client = client
        self._config = dict(config or {})
        self._state: dict[str, Any] = {}

    def bind_state(self, state: dict[str, Any]) -> None:
        self._state = state

    def call(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        """Return response content, or an empty string when no client is configured."""
        del temperature  # provider parameters are fixed when the shared client is built
        return complete_text(
            self._state,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            self._client,
            timeout_s=float(self._config.get("timeout_s", 30.0)),
            max_retry=int(self._config.get("max_retry", 3)),
        )
