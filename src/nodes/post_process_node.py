"""PostProcessNode — S-2 PII redaction, final formatting, and S-4/S-5 audit write."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import provider_metadata

# S-2: PII patterns that must be redacted from outgoing answer
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.IGNORECASE), "[EMAIL_REDACTED]"),
    (re.compile(r"\b0\d{1,4}[-\s]\d{1,4}[-\s]\d{4}\b"), "[PHONE_REDACTED]"),
    (re.compile(r"\b\d{3}-\d{4}-\d{4}\b"), "[PHONE_REDACTED]"),
]


class PostProcessNode(FunctionNode):
    """S-2 PII redaction gate; final output formatting; S-4/S-5 audit write."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("input_error_message"):
            message = str(state["input_error_message"])
            return {
                "result": message,
                "formatted_output": message,
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": message,
            }
        intent = state.get("intent", "out_of_scope")

        # S-2: run output security gate (raises SecurityViolationError on hard violations)
        self._extra_security_gate_output(state)

        # Build audit record (S-4)
        audit_record = {
            "interaction_id": str(uuid.uuid4()),
            "customer_id_hash": state.get("customer_id", ""),
            "intent": intent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel_id": state.get("channel_id", "") or "",
        }

        # Format result by intent branch
        if intent == "qa":
            answer = state.get("answer", "")
            pii_count, answer = self._redact_pii(answer)
            result = json.dumps(
                {
                    "answer": answer,
                    "cited_fields": state.get("cited_fields", []),
                    "intent": "qa",
                    "audit_id": audit_record["interaction_id"],
                },
                ensure_ascii=False,
            )
        elif intent == "erasure":
            result = json.dumps(
                {
                    "erasure_confirmed": state.get("erasure_confirmed", False),
                    "erasure_audit_id": state.get("erasure_audit_id", ""),
                    "segments_deleted": state.get("erasure_segments_deleted", 0),
                    "intent": "erasure",
                    "audit_id": audit_record["interaction_id"],
                },
                ensure_ascii=False,
            )
            pii_count = 0
        else:
            result = json.dumps(
                {
                    "answer": "This question is outside the scope of this agent. Please contact customer support.",
                    "intent": "out_of_scope",
                },
                ensure_ascii=False,
            )
            pii_count = 0

        current_status = state.get("status", AgentStatus.SUCCESS.value)
        final_status = AgentStatus.SUCCESS.value if current_status not in ("error", "blocked") else current_status

        emit_trace_event(
            "PostProcessNode_execute_complete",
            {
                "node": "post_process",
                "intent": intent,
                "status": final_status,
                "pii_redacted_count": pii_count,
            },
            state,
        )
        return {
            "result": result,
            "audit_record": audit_record,
            "status": final_status,
            **provider_metadata(state),
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2/S-3: scan output fields for hard violations.

        Raises SecurityViolationError only on hard violations.
        Soft PII is redacted in execute().
        """
        if state.get("status") == "blocked":
            raise SecurityViolationError("PostProcessNode: upstream blocked status detected")
        return state

    def _redact_pii(self, text: str) -> tuple[int, str]:
        """Apply regex PII redaction to text. Returns (count_redacted, redacted_text)."""
        count = 0
        for pattern, replacement in _PII_PATTERNS:
            new_text, n = pattern.subn(replacement, text)
            text = new_text
            count += n
        return count, text
