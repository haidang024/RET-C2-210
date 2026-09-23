"""PreProcessNode — S-1 input sanitization and customer_id validation gate."""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# S-1: reject email-pattern customer_ids (raw PII)
_EMAIL_PATTERN = re.compile(r"[^@]+@[^@]+\.[^@]+")
# S-1: detect prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"<\s*/?script", re.IGNORECASE),
]
_GREETING_ONLY = re.compile(r"^(?:hello|hi|hey|hello[,. ]*hi|xin chào|chào|こんにちは)[!. ,]*$", re.IGNORECASE)
_INPUT_GUIDANCE = [
    "Provide a question about stored shopping preferences or an explicit erasure request.",
    "Pass customer_id as a hashed or tokenized identifier in input_context.",
    "Do not send an email address, phone number, or other raw customer identity as customer_id.",
]


# Marketplace entrypoint (shared.bootstrap.marketplace_app) hardcodes
# input_context={"conversation_history": ...}, so a caller has no way to pass
# customer_id out-of-band there — the whole JSON envelope arrives as the plain
# message string instead. state.py documents raw_input as "raw invocation
# payload (JSON string or plain query)"; this parses that documented form so
# the Marketplace path can carry customer_id. HTTP /invoke callers that already
# populate input_context are unaffected — those values take precedence.
_ENVELOPE_QUERY_KEYS = ("input", "query_text", "query", "user_input", "message")
_ENVELOPE_MAX_BYTES = 16384


def _parse_envelope(raw_input: str) -> tuple[str, dict[str, Any]]:
    """Split a JSON invocation envelope into (query_text, input_context).

    Returns the input unchanged with an empty context when it is not a JSON
    object — a plain-language question is the normal case, not an error.
    """
    if not isinstance(raw_input, str):
        return "", {}
    candidate = raw_input.strip()
    # Cheap guards before json.loads: only an object can be an envelope, and an
    # oversized blob is rejected by the length cap downstream anyway.
    if not candidate.startswith("{") or len(candidate.encode("utf-8", "ignore")) > _ENVELOPE_MAX_BYTES:
        return raw_input, {}
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return raw_input, {}
    if not isinstance(parsed, dict):
        return raw_input, {}

    query = ""
    for key in _ENVELOPE_QUERY_KEYS:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            query = value
            break

    context = parsed.get("input_context")
    context = dict(context) if isinstance(context, dict) else {}
    # Tolerate a flat envelope that puts the identifiers at the top level.
    for key in ("customer_id", "channel_id"):
        if key not in context and isinstance(parsed.get(key), str):
            context[key] = parsed[key]

    # No recognisable query field: treat the blob as opaque text rather than
    # silently emptying the request.
    return (query if query else raw_input), context


def _resolve_invocation(state: AgentState) -> tuple[str, str, Any]:
    """Resolve (query_text, customer_id, channel_id) from state or envelope."""
    raw_input = state.get("raw_input") or state.get("query_text") or state.get("user_input", "")
    input_context = state.get("input_context") or {}

    query, envelope_context = _parse_envelope(raw_input)
    # Explicit out-of-band context wins; the envelope only fills the gaps.
    customer_id = (
        state.get("customer_id") or input_context.get("customer_id") or envelope_context.get("customer_id", "")
    )
    channel_id = state.get("channel_id") or input_context.get("channel_id") or envelope_context.get("channel_id")
    return query, customer_id, channel_id


def _input_error(message: str) -> dict[str, Any]:
    return {
        "status": AgentStatus.SUCCESS.value,
        "validated_input": "",
        "input_error_message": message,
        "input_error_guidance": _INPUT_GUIDANCE,
    }


class PreProcessNode(FunctionNode):
    """S-1 gate: validate customer_id format, sanitize query_text, check length."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def execute(self, state: AgentState) -> dict[str, Any]:
        state = self._extra_security_gate_input(state)
        if state.get("input_error_message"):
            return _input_error(str(state["input_error_message"]))
        raw_input = state.get("raw_input") or state.get("query_text") or state.get("user_input", "")
        query, customer_id, channel_id = _resolve_invocation(state)

        validated = query.strip()
        emit_trace_event(
            "PreProcessNode_execute_complete",
            {
                "node": "pre_process",
                "customer_id_format_ok": True,
                "query_length": len(validated),
            },
            state,
        )
        return {
            "raw_input": raw_input,
            "query_text": validated,
            "customer_id": customer_id,
            "channel_id": channel_id,
            "validated_input": validated,
            "customer_id_validated": True,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_input(self, state: AgentState) -> AgentState:
        """S-1: customer_id format check + query length cap + injection detection.

        Raises SecurityViolationError if any check fails.
        """
        # Validate the unwrapped question: on the Marketplace path the JSON
        # envelope itself is the message, so checking it raw would length-cap
        # and injection-scan the wrapper rather than the user's actual query.
        raw_input, customer_id, _channel_id = _resolve_invocation(state)

        # Reject empty or obviously too-short queries
        if not raw_input or len(raw_input.strip()) < 1:
            return {**state, **_input_error("Please provide a shopping-context question or erasure request.")}

        if _GREETING_ONLY.fullmatch(raw_input.strip()):
            return {**state, **_input_error("The message contains only a greeting and no customer-context request.")}

        if not customer_id:
            return {**state, **_input_error("customer_id is required as a hashed or tokenized identifier.")}

        # Reject email-format customer_id (raw PII)
        if customer_id and _EMAIL_PATTERN.match(customer_id):
            raise SecurityViolationError("customer_id appears to be raw email address — must be hashed/tokenised")

        # Reject query exceeding max length
        max_length = int(self.config.get("max_query_length", 2048))
        if len(raw_input) > max_length:
            raise SecurityViolationError(f"query_text exceeds {max_length}-character limit (got {len(raw_input)})")

        # Reject injection patterns
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(raw_input):
                raise SecurityViolationError("query_text rejected: potential prompt injection pattern detected")
        return state
