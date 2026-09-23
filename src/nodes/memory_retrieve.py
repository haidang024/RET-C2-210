"""MemoryRetrieveNode — per-customer vector similarity search over Honcho/OpenViking store."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class MemoryRetrieveNode(FunctionNode):
    """Retrieve top-k preference chunks from the per-customer memory store.

    Per-customer_id store isolation is MANDATORY — retrieval must NEVER
    cross customer_id boundaries.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None, memory_store: Any = None) -> None:
        self.config = config or {}
        if memory_store is not None:
            self._memory_store = memory_store
        else:
            from src.services.memory_store_service import MemoryStoreService

            cfg = config or {}
            self._memory_store = MemoryStoreService(
                adapter=cfg.get("memory_store_adapter", "mock"),
                url=cfg.get("memory_store_url", ""),
                api_key=cfg.get("memory_store_api_key", ""),
            )

    def execute(self, state: AgentState) -> dict[str, Any]:
        input_context = state.get("input_context") or {}
        customer_id = state.get("customer_id") or input_context.get("customer_id", "")
        query = state.get("validated_input") or state.get("user_input", "")
        top_k = self.config.get("top_k_memory", 5)

        emit_trace_event(
            "MemoryRetrieveNode_execute_start",
            {"node": "memory_retrieve", "customer_id_hash": customer_id[:8] + "...", "top_k": top_k},
            state,
        )

        try:
            # CRITICAL: customer_id is ALWAYS passed — no global search
            chunks = self._memory_store.search(
                customer_id=customer_id,
                query=query,
                top_k=top_k,
            )
        except (OSError, ConnectionError, RuntimeError, TimeoutError) as exc:
            emit_trace_event(
                "MemoryRetrieveNode_execute_error",
                {"node": "memory_retrieve", "error": str(exc)},
                state,
            )
            chunks = []

        emit_trace_event(
            "MemoryRetrieveNode_execute_complete",
            {
                "node": "memory_retrieve",
                "customer_id_hash": customer_id[:8] + "..." if customer_id else "",
                "chunks_returned": len(chunks),
            },
            state,
        )
        return {"memory_chunks": chunks}
