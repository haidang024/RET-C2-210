"""IntentClassifyNode — LLM-based intent classification for RET-C2-210."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import provider_metadata

_SYSTEM_PROMPT = """You classify retail customer support queries into exactly one of three intents:
- "qa": customer is asking about what AI context/preferences are stored about them
- "erasure": customer is requesting deletion of their stored AI context/preferences (APPI erasure right)
- "out_of_scope": query is about something other than AI-held customer context

Respond with ONLY the intent string — no other text."""

_VALID_INTENTS = frozenset({"qa", "erasure", "out_of_scope"})

# Keyword-based fallback classifiers (used when LLM is unavailable or returns unrecognised value)
_ERASURE_KEYWORDS = [
    "delete",
    "erase",
    "erasure",
    "remove",
    "forget",
    "wipe",
    "削除",
    "消去",
    "個人情報を削除",
    "データを消",
]
_QA_KEYWORDS = [
    "know",
    "stored",
    "store",
    "keep",
    "have",
    "remember",
    "preferences",
    "context",
    "data",
    "information",
    "記録",
    "保存",
    "知って",
    "lactose",
    "recommended",
    "why",
    "what",
    "how",
]


class IntentClassifyNode(FunctionNode):
    """Classify customer query into qa / erasure / out_of_scope."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm: Any = None,
        llm_service: Any = None,
    ) -> None:
        self.config = config or {}
        if llm_service is not None:
            self._llm = llm_service
        else:
            from src.services.llm_service import LLMService

            self._llm = LLMService(client=llm, config=self.config)

    def execute(self, state: AgentState) -> dict[str, Any]:
        validated_input = state.get("validated_input") or state.get("user_input", "")
        if hasattr(self._llm, "bind_state"):
            self._llm.bind_state(state)

        # Try LLM classification first
        intent = self._classify_via_llm(validated_input)

        # Fallback to keyword classification if LLM gave no result
        if intent not in _VALID_INTENTS:
            intent = self._classify_via_keywords(validated_input)

        emit_trace_event(
            "IntentClassifyNode_execute_complete",
            {"node": "intent_classify", "intent": intent},
            state,
        )
        return {"intent": intent, **provider_metadata(state)}

    def _classify_via_llm(self, query: str) -> str:
        """Call LLM and return one of the three intent strings, or "" on failure."""
        try:
            response = str(
                self._llm.call(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=query,
                    temperature=0.0,
                )
            )
            candidate = response.strip().lower().strip('"').strip("'")
            return candidate if candidate in _VALID_INTENTS else ""
        except Exception:
            return ""

    def _classify_via_keywords(self, query: str) -> str:
        """Keyword-based fallback classifier. Defaults to 'qa' if ambiguous."""
        lower = query.lower()
        if any(kw in lower for kw in _ERASURE_KEYWORDS):
            return "erasure"
        if any(kw in lower for kw in _QA_KEYWORDS):
            return "qa"
        return "qa"  # safer default than refusing service
