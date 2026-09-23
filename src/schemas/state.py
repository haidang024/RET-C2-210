"""State schema for RET-C2-210 CustomerContextQAAgent."""

from __future__ import annotations

from typing import Any, Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Flat TypedDict state for RET-C2-210.

    All values must be msgpack-serialisable (str, int, bool, list, dict of primitives).
    No Pydantic objects, no class instances, no secrets in state.

    customer_id MUST be a hashed/tokenised value — never raw PII (email, phone, name).
    """

    # --- Invocation ---
    raw_input: str  # raw invocation payload (JSON string or plain query)
    customer_id: str  # hashed/tokenised customer identifier (MUST NOT be PII)
    query_text: str  # natural language question or erasure command
    channel_id: Optional[str]  # optional — for audit log (chat / app / call_centre)

    # --- After PreProcessNode (S-1) ---
    customer_id_validated: bool  # True if customer_id passed format validation

    # --- After IntentClassifyNode ---

    # --- Q&A branch (MemoryRetrieveNode → RationaleGenerateNode) ---
    memory_chunks: list[dict[str, Any]]  # retrieved preference chunks: [{field, value, score, source}]
    cited_fields: list[str]  # preference field names cited in the answer
    answer: str  # plain-language explanation of stored context

    # --- Erasure branch (ErasureHandlerNode) ---
    erasure_confirmed: bool  # True if hard-delete API confirmed deletion
    erasure_audit_id: Optional[str]  # tamper-evident audit record ID from erasure store
    erasure_segments_deleted: int  # number of memory store segments deleted

    # --- Audit (S-4 / S-5) ---
    audit_record: dict[str, Any]  # {interaction_id, customer_id_hash, intent, timestamp, channel_id}
    input_error_message: str | None
    input_error_guidance: list[str]
    generation_mode: str | None
    provider_error_message: str | None
