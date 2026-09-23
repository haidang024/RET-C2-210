"""RationaleGenerateNode — citation-only LLM synthesis of memory chunks into plain-language answer."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import provider_metadata

_SYSTEM_PROMPT = """You explain to a retail customer what AI context is stored about them.
IMPORTANT: You may ONLY reference preference fields that appear verbatim in the provided context.
Do not infer, extrapolate, or generate information not present in the context.
If context is empty, say: "No AI context is currently stored about you for this topic."

Format your response as a clear, plain-language paragraph."""

_EMPTY_ANSWER = "No AI context is currently stored about you for this topic."


class RationaleGenerateNode(FunctionNode):
    """Synthesise retrieved memory chunks into a citation-only plain-language answer.

    Citation-only constraint: the answer may ONLY reference fields explicitly present
    in memory_chunks — no freeform hallucination beyond retrieved content.
    """

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
        query = state.get("validated_input") or state.get("user_input", "")
        chunks = state.get("memory_chunks", [])
        if hasattr(self._llm, "bind_state"):
            self._llm.bind_state(state)

        emit_trace_event(
            "RationaleGenerateNode_execute_start",
            {"node": "rationale_generate", "chunks_input": len(chunks)},
            state,
        )

        if not chunks:
            emit_trace_event(
                "RationaleGenerateNode_execute_complete",
                {"node": "rationale_generate", "chunks_used": 0, "cited_field_count": 0},
                state,
            )
            return {"answer": _EMPTY_ANSWER, "cited_fields": [], **provider_metadata(state)}

        # Build context string from chunks (only pass fields present in chunks)
        context_lines = [f"- {c.get('field', 'unknown')}: {c.get('value', '')}" for c in chunks]
        context_text = "\n".join(context_lines)
        user_prompt = f"Customer question: {query}\n\nStored context:\n{context_text}"

        try:
            answer = self._llm.call(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
            )
            if not answer or not answer.strip():
                answer = self._deterministic_fallback(chunks)
        except Exception:
            answer = self._deterministic_fallback(chunks)

        # Extract cited fields: only fields that appear in the answer text
        # (citation-only constraint — verified by citing fields from chunks)
        available_fields = [c.get("field", "") for c in chunks if c.get("field")]
        cited_fields = [f for f in available_fields if f and f.lower() in answer.lower()]
        # If LLM gave generic answer without specific fields, default to all chunk fields
        if answer and answer != _EMPTY_ANSWER and not cited_fields:
            cited_fields = available_fields

        emit_trace_event(
            "RationaleGenerateNode_execute_complete",
            {
                "node": "rationale_generate",
                "chunks_used": len(chunks),
                "cited_field_count": len(cited_fields),
            },
            state,
        )
        return {"answer": answer, "cited_fields": cited_fields, **provider_metadata(state)}

    @staticmethod
    def _deterministic_fallback(chunks: list[dict[str, Any]]) -> str:
        """Explain retrieved context without inventing facts when no LLM is available."""
        fields = [f"{chunk.get('field', 'unknown')}: {chunk.get('value', '')}" for chunk in chunks]
        return "Stored AI context: " + "; ".join(fields) + "."
