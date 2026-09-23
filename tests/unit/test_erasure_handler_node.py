# RET-C2-210 — Unit Tests: ErasureHandlerNode
# BL-06, BL-07, PB-5


from framework.schemas.trust_level import TrustLevel
from framework.schemas.agent_status import AgentStatus
from src.nodes.erasure_handler import ErasureHandlerNode


class _MockErasureAPI:
    def delete(self, customer_id: str) -> dict:
        return {"status": "deleted", "segments_deleted": 5, "erasure_id": "era_mock_001"}


class _MockErasureAPIAlwaysFail:
    def delete(self, customer_id: str) -> dict:
        raise RuntimeError("Erasure API unreachable: connection refused")


class _MockErasureAPINotFound:
    """Simulates idempotent case where customer already deleted (not_found)."""

    def delete(self, customer_id: str) -> dict:
        return {"status": "not_found", "segments_deleted": 0, "erasure_id": "era_mock_002"}


class TestErasureHandlerNode:
    """Tests for ErasureHandlerNode — BL-06, BL-07, PB-5."""

    def test_required_trust_level(self):
        """required_trust_level must be VERIFIED_EXTERNAL."""
        assert ErasureHandlerNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    # ── BL-06: Erasure confirmed ──────────────────────────────────────────────

    def test_erasure_confirmed_on_mock_delete(self):
        """BL-06: erasure_confirmed=True when API returns status='deleted'."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPI())
        state = {"customer_id": "cust_hash_abc123"}
        result = node.execute(state)
        assert result["erasure_confirmed"] is True
        assert result["erasure_segments_deleted"] == 5
        assert result["erasure_audit_id"] == "era_mock_001"
        assert result.get("status") == AgentStatus.SUCCESS

    def test_audit_record_written_on_success(self):
        """BL-06: audit_record written with required fields on successful erasure."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPI())
        state = {"customer_id": "cust_hash_abc123"}
        result = node.execute(state)
        assert "audit_record" in result
        audit = result["audit_record"]
        assert "erasure_id" in audit
        assert "customer_id_hash" in audit
        assert "timestamp" in audit
        assert audit["confirmation_status"] == "confirmed"

    # ── BL-07: API failure — never silently fail ──────────────────────────────

    def test_api_failure_returns_erasure_confirmed_false(self):
        """BL-07: erasure_confirmed=False when API raises RuntimeError."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPIAlwaysFail())
        state = {"customer_id": "cust_hash_abc123"}
        result = node.execute(state)
        assert result["erasure_confirmed"] is False
        assert result["status"] == AgentStatus.ERROR
        assert result["erasure_segments_deleted"] == 0

    def test_api_failure_does_not_propagate_exception(self):
        """BL-07: API RuntimeError is caught — no unhandled exception propagates."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPIAlwaysFail())
        state = {"customer_id": "cust_hash_abc123"}
        # Must NOT raise
        result = node.execute(state)
        assert "erasure_confirmed" in result

    def test_missing_customer_id_returns_error(self):
        """Missing customer_id returns error without calling API."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPI())
        state = {"customer_id": ""}
        result = node.execute(state)
        assert result["erasure_confirmed"] is False
        assert result["status"] == AgentStatus.ERROR

    # ── PB-5: Erasure API failure boundary ───────────────────────────────────

    def test_pb5_unreachable_api_graceful_degradation(self):
        """PB-5: Unreachable erasure API → erasure_confirmed=False, error logged, no exception."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPIAlwaysFail())
        state = {"customer_id": "cust_hash_abc123"}
        result = node.execute(state)
        assert result["erasure_confirmed"] is False
        assert result["erasure_segments_deleted"] == 0
        assert result["erasure_audit_id"] is None

    def test_idempotent_not_found_does_not_confirm(self):
        """Idempotent case: not_found response → erasure_confirmed=False (nothing to delete)."""
        node = ErasureHandlerNode(erasure_api=_MockErasureAPINotFound())
        state = {"customer_id": "cust_hash_abc123"}
        result = node.execute(state)
        # not_found → confirmed is False (no data was deleted)
        assert result["erasure_confirmed"] is False
