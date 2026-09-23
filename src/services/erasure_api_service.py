"""ErasureAPIService — hard-delete API client for APPI erasure obligations.

Implements the erasure-API interface contract or direct backend endpoint.
api_key MUST be injected from env var ERASURE_API_KEY — never from config YAML.
"""

from __future__ import annotations

import uuid
from typing import Any


class ErasureAPIService:
    """Hard-delete API client for APPI erasure obligation.

    Calls the erasure endpoint configured in config/config.yaml.
    The API must be idempotent — calling twice for the same customer_id
    must return successfully (not raise on "not found").
    """

    def __init__(self, erasure_api_url: str = "", api_key: str = "") -> None:
        self._erasure_api_url = erasure_api_url
        self._api_key = api_key

    def delete(self, customer_id: str) -> dict[str, Any]:
        """Call hard-delete API for customer_id.

        Idempotent — does not raise if customer_id not found (returns segments_deleted=0).
        Returns: {status: "deleted" | "not_found", segments_deleted: int, erasure_id: str}
        Raises: RuntimeError on HTTP failure (non-2xx response).
        """
        if not customer_id:
            return {"status": "not_found", "segments_deleted": 0, "erasure_id": ""}

        # If URL is empty or points to mock, return mock response
        if not self._erasure_api_url or "mock" in self._erasure_api_url or "localhost" in self._erasure_api_url:
            return self._mock_delete(customer_id=customer_id)

        return self._http_delete(customer_id=customer_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mock_delete(self, customer_id: str) -> dict[str, Any]:
        """Return a mock deletion confirmation (for dev/test)."""
        erasure_id = f"era_{uuid.uuid4().hex[:12]}"
        return {
            "status": "deleted",
            "segments_deleted": 5,
            "erasure_id": erasure_id,
        }

    def _http_delete(self, customer_id: str) -> dict[str, Any]:
        """Perform the real HTTP delete call.

        Raises RuntimeError on non-2xx response.
        """
        try:
            import urllib.request
            import json as _json

            payload = _json.dumps({"customer_id": customer_id}).encode()
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            req = urllib.request.Request(self._erasure_api_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                body = _json.loads(resp.read())
            if not isinstance(body, dict):
                raise RuntimeError("ErasureAPIService: response must be a JSON object")
            return {str(key): value for key, value in body.items()}
        except Exception as exc:
            raise RuntimeError(f"ErasureAPIService: HTTP delete failed: {exc}") from exc
