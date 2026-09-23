# RET-C2-210 — Unit Tests: MemoryRetrieveNode
# BL-04 (cross-customer isolation), PB-4 (absent store)


from framework.schemas.trust_level import TrustLevel
from src.nodes.memory_retrieve import MemoryRetrieveNode


class _MockMemoryStore:
    """Mock memory store that returns customer-specific chunks."""

    def __init__(self, always_fail: bool = False):
        self._always_fail = always_fail
        self._calls: list[tuple] = []

    def search(self, customer_id: str, query: str, top_k: int = 5) -> list[dict]:
        if self._always_fail:
            raise ConnectionError("Mock store unreachable")
        self._calls.append((customer_id, query, top_k))
        return [
            {"field": f"pref_{customer_id[:4]}", "value": "test", "score": 0.9, "source": "mock"},
        ]

    def delete_all(self, customer_id: str) -> dict:
        return {"status": "deleted", "segments_deleted": 1}


class TestMemoryRetrieveNode:
    """Tests for MemoryRetrieveNode — BL-04, PB-4."""

    def test_required_trust_level(self):
        """required_trust_level must be VERIFIED_EXTERNAL."""
        assert MemoryRetrieveNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    # ── BL-04: Cross-customer isolation ──────────────────────────────────────

    def test_customer_id_always_passed_to_store(self):
        """BL-04: customer_id is always scoped when calling memory store."""
        mock_store = _MockMemoryStore()
        node = MemoryRetrieveNode(memory_store=mock_store)

        state = {
            "customer_id": "cust_hash_AAAA",
            "validated_input": "What do you know about my dietary preferences?",
        }
        node.execute(state)

        assert len(mock_store._calls) == 1
        called_customer_id, _, _ = mock_store._calls[0]
        assert called_customer_id == "cust_hash_AAAA"

    def test_isolation_customer_a_does_not_see_customer_b_chunks(self):
        """BL-04: Two customers get different chunks — zero crossover."""
        from src.services.memory_store_service import MemoryStoreService

        # Use real mock adapter which partitions by customer_id
        real_store = MemoryStoreService(adapter="mock")
        node = MemoryRetrieveNode(memory_store=real_store)

        state_a = {
            "customer_id": "cust_AAAA",
            "validated_input": "What is stored about me?",
        }
        state_b = {
            "customer_id": "cust_BBBB",
            "validated_input": "What is stored about me?",
        }
        result_a = node.execute(state_a)
        result_b = node.execute(state_b)

        chunks_a = result_a["memory_chunks"]
        chunks_b = result_b["memory_chunks"]

        # Each customer's chunks contain THEIR customer_id (added by mock)
        for chunk in chunks_a:
            assert (
                chunk.get("customer_id") == "cust_AAAA"
            ), f"Customer A chunk leaked customer_id: {chunk.get('customer_id')}"
        for chunk in chunks_b:
            assert (
                chunk.get("customer_id") == "cust_BBBB"
            ), f"Customer B chunk leaked customer_id: {chunk.get('customer_id')}"

    def test_returns_memory_chunks_key(self):
        """Output must contain 'memory_chunks' key."""
        mock_store = _MockMemoryStore()
        node = MemoryRetrieveNode(memory_store=mock_store)
        state = {"customer_id": "cust_hash_abc", "validated_input": "test query"}
        result = node.execute(state)
        assert "memory_chunks" in result
        assert isinstance(result["memory_chunks"], list)

    def test_returns_empty_on_no_query(self):
        """Empty query returns empty chunks (no crash)."""
        from src.services.memory_store_service import MemoryStoreService

        real_store = MemoryStoreService(adapter="mock")
        node = MemoryRetrieveNode(memory_store=real_store)
        state = {"customer_id": "cust_hash_abc", "validated_input": ""}
        result = node.execute(state)
        assert result["memory_chunks"] == []

    # ── PB-4: Memory store absent / unreachable ───────────────────────────────

    def test_graceful_degradation_when_store_unreachable(self):
        """PB-4: When memory store raises, node returns empty chunks (no exception)."""
        failing_store = _MockMemoryStore(always_fail=True)
        node = MemoryRetrieveNode(memory_store=failing_store)
        state = {
            "customer_id": "cust_hash_abc",
            "validated_input": "What is stored about me?",
        }
        # Should NOT raise — graceful degradation
        result = node.execute(state)
        assert result["memory_chunks"] == []
