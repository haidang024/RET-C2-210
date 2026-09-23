"""Outer Graph for RET-C2-210 — Cat 2 AgentBaseGraph."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.graph.base_graph import BaseGraph
from framework.errors import SubgraphError
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class ContextWorkflowGraphNode(GraphNode):
    """Host the intent-branching customer-context workflow in the main slot."""

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._llm = llm

    def get_subgraph(self) -> BaseGraph:
        from src.graph.domain_workflow_graph import ContextWorkflowGraph

        return ContextWorkflowGraph(config=self._parent_config(), llm=self._llm)

    def extract_input(self, state: AgentState) -> str:
        """Map the outer state to the framework-required string child input."""
        value = state.get("validated_input") or state.get("raw_input") or state.get("user_input", "")
        return value if isinstance(value, str) else str(value)

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Merge both Q&A and erasure branch fields into the outer state."""
        del state
        return {
            "generation_mode": sub_result.get("generation_mode"),
            "provider_error_message": sub_result.get("provider_error_message"),
            "intent": sub_result.get("intent", "out_of_scope"),
            "memory_chunks": sub_result.get("memory_chunks", []),
            "cited_fields": sub_result.get("cited_fields", []),
            "answer": sub_result.get("answer", ""),
            "erasure_confirmed": sub_result.get("erasure_confirmed", False),
            "erasure_audit_id": sub_result.get("erasure_audit_id"),
            "erasure_segments_deleted": sub_result.get("erasure_segments_deleted", 0),
            "status": sub_result.get("status", AgentStatus.SUCCESS.value),
        }

    def execute(self, state: AgentState) -> dict[str, Any]:
        """Delegate while preserving customer scope across the subgraph boundary."""
        if state.get("input_error_message"):
            return {"status": AgentStatus.SUCCESS.value}
        ctx = replace(InvocationContext.from_state(state), hitl_allowed=False)
        subgraph = self.get_subgraph()
        input_context = dict(state.get("input_context") or {})
        input_context.update(
            {
                "customer_id": state.get("customer_id", ""),
                "channel_id": state.get("channel_id"),
            }
        )
        try:
            sub_result = subgraph.invoke(
                self.extract_input(state),
                session_id=ctx.session_id,
                ctx=ctx,
                input_context=input_context,
            )
        except Exception as exc:
            return dict(self._handle_call_error(subgraph, exc, state))
        if sub_result.get("status") == AgentStatus.ERROR.value:
            error = SubgraphError(
                agent_name=subgraph.name,
                error_log=sub_result.get("error_log", []),
                trace_id=sub_result.get("trace_id", ""),
            )
            if self.error_strategy == "propagate":
                raise error
            return cast(dict[str, Any], self.on_subgraph_error(state, error))
        return self.merge_output(state, sub_result)

    def _parent_config(self) -> dict[str, Any]:
        """Return only runtime settings consumed by the child workflow."""
        return {
            "memory_store_adapter": self.config.get("memory_store_adapter", "mock"),
            "memory_store_url": self.config.get("memory_store_url", ""),
            "top_k_memory": self.config.get("top_k_memory", 5),
            "embedding_model": self.config.get("embedding_model", "text-embedding-3-small"),
            "erasure_api_url": self.config.get("erasure_api_url", "http://localhost:8001/erase"),
            "llm_model": self.config.get("llm_model", "azure-openai-deployment"),
            "temperature_classify": self.config.get("temperature_classify", 0.0),
            "temperature_generate": self.config.get("temperature_generate", 0.1),
            "timeout_s": self.config.get("timeout_s", 30.0),
            "max_retry": self.config.get("max_retry", 3),
        }


class Graph(AgentBaseGraph):
    """Customer context Q&A and erasure orchestration agent."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    @property
    def name(self) -> str:
        return "RetailCustomerContextQAAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()
        self._nodes["pre_process"] = PreProcessNode(config=self.config)
        self._nodes["main"] = ContextWorkflowGraphNode(
            llm=self.config.get("llm"),
            config=self.config,
        )
        self._nodes["post_process"] = PostProcessNode(config=self.config)

    def get_output(self, state: AgentState) -> dict[str, Any]:
        output = {
            "output": state.get("result", ""),
            "result": state.get("result", ""),
            "status": state.get("status", AgentStatus.ERROR.value),
            "intent": state.get("intent", ""),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "generation_mode": state.get("generation_mode"),
            "provider_error_message": state.get("provider_error_message"),
        }
        context = state.get("input_context")
        is_marketplace = isinstance(context, dict) and "conversation_history" in context
        if not is_marketplace:
            return output
        if _set_marketplace_guidance(output, state, "Customer shopping-context request"):
            return output
        payload = self._parse_payload(output.get("output", output.get("formatted_output")))
        if payload is not None:
            output["output"] = self._render_marketplace_response(payload)
        return output

    @staticmethod
    def _parse_payload(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _render_marketplace_response(payload: dict[str, Any]) -> str:
        intent = str(payload.get("intent", "out_of_scope"))
        if intent == "erasure":
            confirmed = bool(payload.get("erasure_confirmed"))
            lines = [
                "# Customer Data Erasure",
                "",
                f"**Status:** {'Completed' if confirmed else 'Not completed'}",
                f"**Segments deleted:** {payload.get('segments_deleted', 0)}",
            ]
            if payload.get("erasure_audit_id"):
                lines.append(f"**Erasure reference:** {payload['erasure_audit_id']}")
            return "\n".join(lines)

        lines = ["# Customer Shopping Context Answer", "", str(payload.get("answer", "No answer was generated."))]
        cited_fields = payload.get("cited_fields")
        if isinstance(cited_fields, list) and cited_fields:
            lines.extend(["", "## Context fields used", ""])
            lines.extend(f"- {field}" for field in cited_fields)
        return "\n".join(lines)


def _set_marketplace_guidance(output: dict[str, Any], state: AgentState, subject: str) -> bool:
    context = state.get("input_context")
    message = state.get("input_error_message")
    if not (isinstance(context, dict) and "conversation_history" in context and message):
        return False
    lines = [f"{subject} could not be processed.", "", f"Reason: {message}"]
    guidance = state.get("input_error_guidance")
    if isinstance(guidance, list) and guidance:
        lines.extend(["", "How to continue:"])
        lines.extend(f"- {item}" for item in guidance)
    output["output"] = "\n".join(lines)
    return True
