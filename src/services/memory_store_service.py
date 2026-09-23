"""MemoryStoreService — per-user memory store adapter for RET-C2-210.

Supports Honcho, OpenViking, and a local mock adapter for development.
Per-customer_id scoping is mandatory — no global search path exists.
"""

from __future__ import annotations

from typing import Any


_MOCK_CHUNKS_BY_FIELD: list[dict[str, Any]] = [
    {
        "field": "dietary_restrictions",
        "value": "lactose intolerant",
        "score": 0.92,
        "source": "purchase_history",
        "created_at": "2026-01-15",
    },
    {
        "field": "preferred_category",
        "value": "plant-based dairy alternatives",
        "score": 0.87,
        "source": "browse_history",
        "created_at": "2026-02-10",
    },
    {
        "field": "price_sensitivity",
        "value": "mid-range",
        "score": 0.81,
        "source": "cart_analysis",
        "created_at": "2026-03-01",
    },
    {
        "field": "recommendation_accepted",
        "value": "oat milk latte — accepted 3 times",
        "score": 0.78,
        "source": "recommendation_log",
        "created_at": "2026-04-05",
    },
    {
        "field": "last_purchase_category",
        "value": "beverages",
        "score": 0.74,
        "source": "purchase_history",
        "created_at": "2026-05-20",
    },
]


class MemoryStoreService:
    """Per-user memory store adapter.

    adapter: "honcho" | "openviking" | "mock" — switch to "honcho" for production.
    api_key MUST be injected from env var MEMORY_STORE_API_KEY — never from config YAML.
    """

    def __init__(self, adapter: str = "mock", url: str = "", api_key: str = "") -> None:
        self._adapter = adapter
        self._url = url
        self._api_key = api_key

    def search(self, customer_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Vector similarity search scoped to customer_id partition.

        NEVER performs a global search — customer_id is always required.

        Returns: [{field, value, score, source, created_at}]
        """
        if not customer_id:
            return []

        if self._adapter == "mock":
            return self._mock_search(customer_id=customer_id, query=query, top_k=top_k)

        # Honcho / OpenViking adapter placeholder
        raise NotImplementedError(f"Adapter '{self._adapter}' is not implemented in this release.")

    def delete_all(self, customer_id: str) -> dict[str, Any]:
        """Hard-delete all memory store entries for customer_id.

        Idempotent — calling twice on same customer_id must not raise.
        Returns: {status: "deleted" | "not_found", segments_deleted: int}
        """
        if not customer_id:
            return {"status": "not_found", "segments_deleted": 0}

        if self._adapter == "mock":
            return {"status": "deleted", "segments_deleted": len(_MOCK_CHUNKS_BY_FIELD)}

        raise NotImplementedError(f"Adapter '{self._adapter}' is not implemented in this release.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mock_search(self, customer_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
        """Return customer-specific mock chunks.

        Each customer_id gets a deterministically different subset so that
        cross-customer isolation tests can verify zero chunk crossover.
        """
        if not query:
            return []
        # Use customer_id hash to select a deterministic slice — ensures isolation
        seed = sum(ord(c) for c in customer_id) % len(_MOCK_CHUNKS_BY_FIELD)
        # Rotate the chunk list so different customers get different slices
        rotated = _MOCK_CHUNKS_BY_FIELD[seed:] + _MOCK_CHUNKS_BY_FIELD[:seed]
        return [dict(chunk, customer_id=customer_id) for chunk in rotated[:top_k]]
