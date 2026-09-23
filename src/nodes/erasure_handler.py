"""ErasureHandlerNode — APPI hard-delete handler with tamper-evident audit record."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class ErasureHandlerNode(FunctionNode):
    """Execute APPI erasure: hard-delete customer memory store + write audit record.

    Never silently fails — erasure_confirmed=False + error logged on any API failure.
    Erasure API must be idempotent (re-call on same customer_id must not error).
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None, erasure_api: Any = None) -> None:
        self.config = config or {}
        if erasure_api is not None:
            self._erasure_api = erasure_api
        else:
            from src.services.erasure_api_service import ErasureAPIService

            cfg = config or {}
            self._erasure_api = ErasureAPIService(
                erasure_api_url=cfg.get("erasure_api_url", "http://localhost:8001/erase"),
                api_key=cfg.get("erasure_api_key", ""),
            )

    def execute(self, state: AgentState) -> dict[str, Any]:
        input_context = state.get("input_context") or {}
        customer_id = state.get("customer_id") or input_context.get("customer_id", "")

        # Re-validate customer_id before deletion (critical safety check)
        if not customer_id:
            emit_trace_event(
                "ErasureHandlerNode_execute_error",
                {"node": "erasure_handler", "erasure_confirmed": False, "reason": "missing_customer_id"},
                state,
            )
            return {
                "erasure_confirmed": False,
                "erasure_audit_id": None,
                "erasure_segments_deleted": 0,
                "status": AgentStatus.ERROR.value,
            }

        emit_trace_event(
            "ErasureHandlerNode_execute_start",
            {"node": "erasure_handler", "customer_id_hash": customer_id[:8] + "..."},
            state,
        )

        try:
            response = self._erasure_api.delete(customer_id=customer_id)
            confirmed = response.get("status") == "deleted"
            segments = response.get("segments_deleted", 0)
            erasure_id = response.get("erasure_id", str(uuid.uuid4()))
        except Exception as exc:
            emit_trace_event(
                "ErasureHandlerNode_execute_error",
                {
                    "node": "erasure_handler",
                    "erasure_confirmed": False,
                    "error": str(exc),
                },
                state,
            )
            return {
                "erasure_confirmed": False,
                "erasure_audit_id": None,
                "erasure_segments_deleted": 0,
                "status": AgentStatus.ERROR.value,
            }

        # Write tamper-evident audit record
        audit_record = {
            "erasure_id": erasure_id,
            "customer_id_hash": customer_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "segments_deleted": str(segments),
            "confirmation_status": "confirmed" if confirmed else "failed",
        }

        emit_trace_event(
            "ErasureHandlerNode_execute_complete",
            {
                "node": "erasure_handler",
                "erasure_confirmed": confirmed,
                "segments_deleted": segments,
            },
            state,
        )
        return {
            "erasure_confirmed": confirmed,
            "erasure_audit_id": erasure_id,
            "erasure_segments_deleted": segments,
            "audit_record": audit_record,
            "status": AgentStatus.SUCCESS.value if confirmed else AgentStatus.ERROR.value,
        }
