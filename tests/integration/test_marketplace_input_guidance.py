import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


def test_invalid_marketplace_request_returns_readable_guidance():
    graph = Graph(config={})
    graph.compile()
    result = graph.invoke(
        "Hello, hi",
        ctx=InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL),
        input_context={"conversation_history": []},
    )

    assert result["status"] == "success"
    assert result["output"].startswith("Customer shopping-context request could not be processed.")
    assert "Reason:" in result["output"]
    assert "How to continue:" in result["output"]


def test_success_output_is_readable_only_for_marketplace():
    graph = Graph(config={})
    canonical = json.dumps(
        {
            "answer": "Your saved preference is the standard delivery window.",
            "cited_fields": ["delivery_preference"],
            "intent": "qa",
            "audit_id": "audit-123",
        }
    )
    state = {"result": canonical, "status": "success"}

    assert graph.get_output(state)["output"] == canonical

    marketplace = graph.get_output({**state, "input_context": {"conversation_history": []}})
    assert marketplace["output"].startswith("# Customer Shopping Context Answer")
    assert "Your saved preference is the standard delivery window." in marketplace["output"]
    assert not marketplace["output"].lstrip().startswith("{")
