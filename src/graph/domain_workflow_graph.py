"""Inner intent-branching customer context workflow for RET-C2-210."""

from __future__ import annotations

from typing import Any

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from langgraph.graph import END, START
from src.nodes.erasure_handler import ErasureHandlerNode
from src.nodes.intent_classify import IntentClassifyNode
from src.nodes.memory_retrieve import MemoryRetrieveNode
from src.nodes.rationale_generate import RationaleGenerateNode
from src.schemas.state import State


class ContextWorkflowGraph(BaseGraph):
    """Classify intent, then run the scoped Q&A or erasure branch."""

    def __init__(self, config: dict[str, Any] | None = None, llm: Any = None) -> None:
        self._llm = llm
        super().__init__(config=config)

    @property
    def name(self) -> str:
        return "ret_c2_210_context_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        adapter = self.config.get("memory_store_adapter", "mock")
        if adapter not in {"mock", "honcho", "openviking"}:
            raise ValueError(f"Unsupported memory_store_adapter: {adapter}")

    def register_nodes(self) -> None:
        """Wire both LLM nodes to the one client injected by the server."""
        self._nodes["intent_classify"] = IntentClassifyNode(
            config=self.config,
            llm=self._llm,
        )
        self._nodes["memory_retrieve"] = MemoryRetrieveNode(config=self.config)
        self._nodes["rationale_generate"] = RationaleGenerateNode(
            config=self.config,
            llm=self._llm,
        )
        self._nodes["erasure_handler"] = ErasureHandlerNode(config=self.config)

    def add_edges(self) -> None:
        assert self._sg is not None
        self._sg.add_edge(START, "intent_classify")
        self._sg.add_conditional_edges("intent_classify", self._route_intent)
        self._sg.add_edge("memory_retrieve", "rationale_generate")
        self._sg.add_edge("rationale_generate", END)
        self._sg.add_edge("erasure_handler", END)

    def route(self, state: AgentState) -> str:
        del state
        return "intent_classify"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "generation_mode": state.get("generation_mode"),
            "provider_error_message": state.get("provider_error_message"),
            "intent": state.get("intent", "out_of_scope"),
            "memory_chunks": state.get("memory_chunks", []),
            "cited_fields": state.get("cited_fields", []),
            "answer": state.get("answer", ""),
            "erasure_confirmed": state.get("erasure_confirmed", False),
            "erasure_audit_id": state.get("erasure_audit_id"),
            "erasure_segments_deleted": state.get("erasure_segments_deleted", 0),
            "audit_record": state.get("audit_record", {}),
            "status": (
                AgentStatus.ERROR.value if state.get("status") == AgentStatus.ERROR.value else AgentStatus.SUCCESS.value
            ),
        }

    def _route_intent(self, state: AgentState) -> str:
        intent = state.get("intent", "out_of_scope")
        if intent == "qa":
            return "memory_retrieve"
        if intent == "erasure":
            return "erasure_handler"
        return str(END)
